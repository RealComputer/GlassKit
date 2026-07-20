from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol, cast

from .checkpoints import CheckpointStore, attach_checkpoint, checkpoint_plan_hash
from .compare import compare_observation
from .execution import (
    EvaluationOutcome,
    FrameCursor,
    close_evaluator,
    evaluate_samples,
    load_configured_evaluator,
)
from .expectations import load_eval_directory
from .models import (
    AdapterConfig,
    EvalCase,
    EvalConfigError,
    EvalDirectory,
    EvalRunReport,
    EvalTrialReport,
    EvaluationTimingMode,
    FrameSample,
    GateResult,
    ResultStatus,
    RunOptions,
    SampleExpectation,
    SampleResult,
    SampleStability,
    TargetContext,
    Thresholds,
    ValidationIssue,
    ValidationReport,
)
from .video import iter_sample_frames, probe_video, validate_sample_times


class RunCallbacks(Protocol):
    def on_checkpoint(self, path: Path) -> None: ...

    def on_trial_start(self, trial_index: int, trial_count: int) -> None: ...

    def on_case_start(self, case: EvalCase, sample_count: int) -> None: ...

    def on_target_start(
        self, case: EvalCase, target_id: str, sample_count: int
    ) -> None: ...

    def on_result(self, result: SampleResult) -> None: ...


async def validate_eval_directory(options: RunOptions) -> ValidationReport:
    issues: list[ValidationIssue] = []
    eval_directory: EvalDirectory | None = None
    try:
        eval_directory = load_eval_directory(
            options.eval_dir,
            case_filter=options.case_filter,
            target_filter=options.target_filter,
            allow_empty=options.allow_empty,
        )
    except EvalConfigError as error:
        return ValidationReport(
            eval_directory=None,
            issues=[ValidationIssue(message=str(error), path=options.eval_dir)],
        )

    issues.extend(_validate_videos(eval_directory))
    if options.adapter is not None and options.adapter_command is not None:
        issues.append(
            ValidationIssue(
                message="adapter and adapter command are mutually exclusive"
            )
        )
    elif options.adapter is not None or options.adapter_command is not None:
        try:
            evaluator = await load_configured_evaluator(
                options.adapter,
                options.adapter_command,
                AdapterConfig(
                    eval_dir=eval_directory.path,
                    config=options.adapter_config,
                    artifacts_dir=options.artifacts_dir,
                    verbose=options.verbose,
                ),
            )
            await evaluator.close()
        except Exception as error:
            issues.append(
                ValidationIssue(message=f"adapter validation failed: {error}")
            )
    return ValidationReport(eval_directory=eval_directory, issues=issues)


async def run_eval(
    options: RunOptions, callbacks: RunCallbacks | None = None
) -> EvalRunReport:
    if options.adapter is not None and options.adapter_command is not None:
        raise EvalConfigError("adapter and adapter command are mutually exclusive")
    if options.adapter is None and options.adapter_command is None:
        raise EvalConfigError(
            "glasskit eval run requires --adapter or --adapter-command"
        )
    if options.concurrency < 1:
        raise EvalConfigError("concurrency must be greater than 0")
    if options.repeat < 1:
        raise EvalConfigError("repeat must be greater than 0")
    if options.max_flaky_samples is not None:
        if options.max_flaky_samples < 0:
            raise EvalConfigError("max flaky samples must be nonnegative")
        if options.repeat < 2:
            raise EvalConfigError(
                "--max-flaky-samples requires --repeat to be at least 2"
            )
    started_at = perf_counter()
    eval_directory = load_eval_directory(
        options.eval_dir,
        case_filter=options.case_filter,
        target_filter=options.target_filter,
        from_time_s=options.from_time_s,
        until_time_s=options.until_time_s,
        allow_empty=options.allow_empty,
    )
    validation_issues = _validate_videos(eval_directory)
    error_messages = [
        issue.message for issue in validation_issues if issue.severity == "error"
    ]
    if error_messages:
        raise EvalConfigError("; ".join(error_messages))

    invocation = run_checkpoint_invocation(options)
    plan_hash = checkpoint_plan_hash(eval_directory, invocation)
    planned_samples = {
        _run_result_key(trial_index, sample): sample
        for trial_index in range(1, options.repeat + 1)
        for case in eval_directory.cases
        for sample in case.samples
    }
    checkpoint = (
        CheckpointStore.resume(
            eval_dir=eval_directory.path,
            reference=options.resume_checkpoint,
            kind="run",
            plan_hash=plan_hash,
        )
        if options.resume_checkpoint is not None
        else CheckpointStore.create(
            kind="run",
            eval_dir=eval_directory.path,
            invocation=invocation,
            plan_hash=plan_hash,
            total=len(planned_samples),
        )
    )
    if callbacks is not None and callable(
        on_checkpoint := getattr(callbacks, "on_checkpoint", None)
    ):
        on_checkpoint(checkpoint.path)

    try:
        saved_results = checkpoint.latest("run_result")
        _validate_run_checkpoint_keys(saved_results, planned_samples, checkpoint.path)
        trials: list[EvalTrialReport] = []
        for trial_index in range(1, options.repeat + 1):
            if callbacks is not None:
                callbacks.on_trial_start(trial_index, options.repeat)
            trials.append(
                await _run_trial(
                    eval_directory,
                    options=options,
                    trial_index=trial_index,
                    callbacks=callbacks,
                    checkpoint=checkpoint,
                    saved_results=saved_results,
                )
            )

        stability = _summarize_stability(trials)
        resumable_error_count = sum(
            _is_resumable_adapter_error(result)
            for trial in trials
            for result in trial.results
        )
        report = EvalRunReport(
            eval_dir=eval_directory.path,
            case_names=[case.name for case in eval_directory.cases],
            trials=trials,
            stability=stability,
            gate_results=_apply_stability_gates(stability, options),
            duration_s=max(0.0, perf_counter() - started_at),
            checkpoint_path=checkpoint.path,
            resumed=options.resume_checkpoint is not None,
            resumable_error_count=resumable_error_count,
        )
        if resumable_error_count == 0:
            checkpoint.mark_complete()
        if options.output_json is not None:
            write_json_report(report, options.output_json)
        return report
    except BaseException as error:
        attach_checkpoint(error, checkpoint)
        raise
    finally:
        checkpoint.release()


async def _run_trial(
    eval_directory: EvalDirectory,
    *,
    options: RunOptions,
    trial_index: int,
    callbacks: RunCallbacks | None,
    checkpoint: CheckpointStore,
    saved_results: dict[str, dict[str, Any]],
) -> EvalTrialReport:
    started_at = perf_counter()
    if options.adapter is None and options.adapter_command is None:
        raise RuntimeError("internal error: trial started without an adapter")
    pending_evaluations = [
        sample
        for case in eval_directory.cases
        for sample in case.samples
        if sample.ignore is None
        and not _checkpoint_result_is_complete(
            saved_results.get(_run_result_key(trial_index, sample))
        )
    ]
    evaluator = (
        await load_configured_evaluator(
            options.adapter,
            options.adapter_command,
            AdapterConfig(
                eval_dir=eval_directory.path,
                config=options.adapter_config,
                artifacts_dir=options.artifacts_dir,
                verbose=options.verbose,
            ),
        )
        if pending_evaluations
        else None
    )

    results: list[SampleResult] = []
    try:
        for case in eval_directory.cases:
            case_samples = case.samples
            pending_case_samples = [
                sample
                for sample in case_samples
                if not _checkpoint_result_is_complete(
                    saved_results.get(_run_result_key(trial_index, sample))
                )
            ]
            evaluated_case_samples = [
                sample for sample in pending_case_samples if sample.ignore is None
            ]
            if callbacks is not None and pending_case_samples:
                callbacks.on_case_start(case, len(pending_case_samples))
            frame_cursor = FrameCursor(
                iter_sample_frames(
                    case.video_path,
                    evaluated_case_samples,
                    case_name=case.name,
                )
            )
            try:
                for target in case.targets:
                    target_samples = target.samples
                    if not target_samples:
                        continue
                    pending_target_samples = [
                        sample
                        for sample in target_samples
                        if not _checkpoint_result_is_complete(
                            saved_results.get(_run_result_key(trial_index, sample))
                        )
                    ]
                    if callbacks is not None and pending_target_samples:
                        callbacks.on_target_start(
                            case, target.id, len(pending_target_samples)
                        )
                    context = TargetContext(
                        id=target.id,
                        index=target.index,
                        label=target.label,
                        config=target.config,
                    )
                    evaluated_target_samples = [
                        sample
                        for sample in pending_target_samples
                        if sample.ignore is None
                    ]
                    evaluated_results = {
                        result.sample_index: result
                        for result in (
                            await evaluate_samples(
                                evaluator,
                                frame_cursor,
                                evaluated_target_samples,
                                context,
                                concurrency=options.concurrency,
                                keep_going=options.keep_going,
                                transform=lambda evaluation, frame: (
                                    _checkpoint_run_result(
                                        _result_for_frame(
                                            evaluation,
                                            frame,
                                            options=options,
                                            eval_dir=eval_directory.path,
                                            trial_index=trial_index,
                                        ),
                                        trial_index=trial_index,
                                        checkpoint=checkpoint,
                                        saved_results=saved_results,
                                        callbacks=callbacks,
                                    )
                                ),
                            )
                            if evaluated_target_samples and evaluator is not None
                            else []
                        )
                    }
                    for sample in target_samples:
                        key = _run_result_key(trial_index, sample)
                        if result_payload := saved_results.get(key):
                            if _checkpoint_result_is_complete(result_payload):
                                result = _result_from_checkpoint(sample, result_payload)
                            else:
                                result = evaluated_results[sample.sample_index]
                        elif sample.ignore is not None:
                            result = _checkpoint_run_result(
                                _ignored_result(sample),
                                trial_index=trial_index,
                                checkpoint=checkpoint,
                                saved_results=saved_results,
                                callbacks=callbacks,
                            )
                        else:
                            result = evaluated_results[sample.sample_index]
                        results.append(result)
            finally:
                frame_cursor.close()
    finally:
        if evaluator is not None:
            await close_evaluator(evaluator)

    gate_results = _apply_quality_gates(eval_directory, results, options)
    return EvalTrialReport(
        index=trial_index,
        results=results,
        gate_results=gate_results,
        duration_s=max(0.0, perf_counter() - started_at),
    )


def run_checkpoint_invocation(options: RunOptions) -> dict[str, Any]:
    return {
        "eval_dir": str(options.eval_dir.expanduser().resolve()),
        "adapter": options.adapter,
        "adapter_command": options.adapter_command,
        "case_filter": options.case_filter,
        "target_filter": (
            list(options.target_filter)
            if isinstance(options.target_filter, tuple)
            else options.target_filter
        ),
        "from_time_s": options.from_time_s,
        "until_time_s": options.until_time_s,
        "adapter_config": dict(options.adapter_config),
        "concurrency": options.concurrency,
        "repeat": options.repeat,
        "min_pass_rate": options.min_pass_rate,
        "min_target_pass_rate": options.min_target_pass_rate,
        "max_failures": options.max_failures,
        "max_flaky_samples": options.max_flaky_samples,
        "keep_going": options.keep_going,
        "verbose": options.verbose,
        "output_json": str(options.output_json) if options.output_json else None,
        "artifacts_dir": (
            str(options.artifacts_dir) if options.artifacts_dir else None
        ),
        "save_failures": options.save_failures,
        "allow_empty": options.allow_empty,
    }


def run_options_from_invocation(
    invocation: Mapping[str, Any],
    *,
    checkpoint_path: Path,
    verbose: bool,
) -> RunOptions:
    target_filter = invocation.get("target_filter")
    if isinstance(target_filter, list):
        target_filter = tuple(str(value) for value in target_filter)
    adapter_config = invocation.get("adapter_config", {})
    if not isinstance(adapter_config, Mapping):
        raise EvalConfigError("run checkpoint adapter_config must be an object")
    return RunOptions(
        eval_dir=Path(str(invocation.get("eval_dir", "eval"))),
        adapter=_optional_checkpoint_string(invocation.get("adapter")),
        adapter_command=_optional_checkpoint_string(invocation.get("adapter_command")),
        case_filter=_optional_checkpoint_string(invocation.get("case_filter")),
        target_filter=target_filter,
        from_time_s=_optional_number(invocation.get("from_time_s")),
        until_time_s=_optional_number(invocation.get("until_time_s")),
        adapter_config=dict(adapter_config),
        concurrency=int(invocation.get("concurrency", 1)),
        repeat=int(invocation.get("repeat", 1)),
        min_pass_rate=_optional_number(invocation.get("min_pass_rate")),
        min_target_pass_rate=_optional_number(invocation.get("min_target_pass_rate")),
        max_failures=_optional_integer(invocation.get("max_failures")),
        max_flaky_samples=_optional_integer(invocation.get("max_flaky_samples")),
        keep_going=invocation.get("keep_going") is True,
        verbose=verbose or invocation.get("verbose") is True,
        output_json=_optional_checkpoint_path(invocation.get("output_json")),
        artifacts_dir=_optional_checkpoint_path(invocation.get("artifacts_dir")),
        save_failures=invocation.get("save_failures") is True,
        allow_empty=invocation.get("allow_empty") is True,
        resume_checkpoint=checkpoint_path,
    )


def _checkpoint_run_result(
    result: SampleResult,
    *,
    trial_index: int,
    checkpoint: CheckpointStore,
    saved_results: dict[str, dict[str, Any]],
    callbacks: RunCallbacks | None,
) -> SampleResult:
    key = _run_result_key_for_result(trial_index, result)
    payload = _result_to_json(result)
    checkpoint.record("run_result", key, payload)
    saved_results[key] = payload
    return _report_result(result, callbacks=callbacks)


def _checkpoint_result_is_complete(payload: Mapping[str, Any] | None) -> bool:
    if payload is None:
        return False
    return not (
        payload.get("status") == "error"
        and isinstance(payload.get("reason"), str)
        and payload["reason"].startswith("adapter_error:")
    )


def _is_resumable_adapter_error(result: SampleResult) -> bool:
    return result.status == "error" and result.reason.startswith("adapter_error:")


def _result_from_checkpoint(
    sample: SampleExpectation, payload: Mapping[str, Any]
) -> SampleResult:
    identity = (
        payload.get("case"),
        payload.get("target"),
        payload.get("sample_index"),
        payload.get("timestamp_s"),
    )
    expected_identity = (
        sample.case_name,
        sample.target_id,
        sample.sample_index,
        sample.timestamp_s,
    )
    if identity != expected_identity:
        raise EvalConfigError(
            "checkpoint result identity does not match the current sample plan for "
            f"{sample.case_name}/{sample.target_id} sample {sample.sample_index}"
        )
    status = payload.get("status")
    if status not in {"passed", "failed", "error", "ignored"}:
        raise EvalConfigError(
            f"checkpoint contains an invalid result status for {sample.case_name}/"
            f"{sample.target_id} sample {sample.sample_index}"
        )
    duration = payload.get("evaluation_duration_seconds")
    if duration is not None and (
        not isinstance(duration, (int, float)) or isinstance(duration, bool)
    ):
        raise EvalConfigError("checkpoint contains an invalid evaluation duration")
    timing_mode = payload.get("evaluation_timing_mode")
    if timing_mode not in {None, "individual", "batch_amortized"}:
        raise EvalConfigError("checkpoint contains an invalid evaluation timing mode")
    return SampleResult(
        case_name=sample.case_name,
        target_id=sample.target_id,
        target_label=sample.target_label,
        sample_index=sample.sample_index,
        timestamp_s=sample.timestamp_s,
        status=cast(ResultStatus, status),
        expected=sample.expected,
        observed=payload.get("observed"),
        observed_value=payload.get("observed_value"),
        compare_mode=sample.compare.mode,
        field=sample.field,
        reason=str(payload.get("reason", "")),
        source=sample.source,
        evaluation_duration_s=float(duration) if duration is not None else None,
        evaluation_timing_mode=cast(EvaluationTimingMode | None, timing_mode),
        artifact_image=_optional_checkpoint_string(payload.get("artifact_image")),
        artifact_json=_optional_checkpoint_string(payload.get("artifact_json")),
    )


def _validate_run_checkpoint_keys(
    saved: Mapping[str, Any],
    planned: Mapping[str, SampleExpectation],
    checkpoint_path: Path,
) -> None:
    if set(saved) - set(planned):
        raise EvalConfigError(
            f"checkpoint contains results outside the selected run plan: "
            f"{checkpoint_path}"
        )


def _run_result_key(trial_index: int, sample: SampleExpectation) -> str:
    return (
        f"{trial_index}\u0000{sample.case_name}\u0000{sample.target_id}\u0000"
        f"{sample.sample_index}\u0000{float(sample.timestamp_s).hex()}"
    )


def _run_result_key_for_result(trial_index: int, result: SampleResult) -> str:
    return (
        f"{trial_index}\u0000{result.case_name}\u0000{result.target_id}\u0000"
        f"{result.sample_index}\u0000{float(result.timestamp_s).hex()}"
    )


def _optional_checkpoint_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_checkpoint_path(value: Any) -> Path | None:
    return Path(value) if isinstance(value, str) else None


def _optional_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ignored_result(sample: SampleExpectation) -> SampleResult:
    if sample.ignore is None:
        raise ValueError("ignored results require an ignore reason")
    return SampleResult(
        case_name=sample.case_name,
        target_id=sample.target_id,
        target_label=sample.target_label,
        sample_index=sample.sample_index,
        timestamp_s=sample.timestamp_s,
        status="ignored",
        expected=sample.expected,
        observed=None,
        observed_value=None,
        compare_mode=sample.compare.mode,
        field=sample.field,
        reason=sample.ignore,
        source=sample.source,
    )


def _report_result(
    result: SampleResult, *, callbacks: RunCallbacks | None
) -> SampleResult:
    if callbacks is not None:
        callbacks.on_result(result)
    return result


def write_json_report(report: EvalRunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_report_to_json(report), ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _validate_videos(eval_directory: EvalDirectory) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for case in eval_directory.cases:
        try:
            metadata = probe_video(case.video_path)
        except EvalConfigError as error:
            issues.append(ValidationIssue(message=str(error), path=case.video_path))
            continue
        for message in validate_sample_times(case.samples, metadata):
            issues.append(ValidationIssue(message=message, path=case.video_path))
    return issues


def _result_for_evaluation(
    evaluation: EvaluationOutcome, *, options: RunOptions
) -> SampleResult:
    sample = evaluation.sample
    observation = evaluation.observation
    runtime_error = evaluation.runtime_error
    if runtime_error is not None:
        return SampleResult(
            case_name=sample.case_name,
            target_id=sample.target_id,
            target_label=sample.target_label,
            sample_index=sample.sample_index,
            timestamp_s=sample.timestamp_s,
            status="error",
            expected=sample.expected,
            observed=None,
            observed_value=None,
            compare_mode=sample.compare.mode,
            field=sample.field,
            reason=f"adapter_error: {runtime_error}",
            source=sample.source,
            evaluation_duration_s=evaluation.duration_s,
            evaluation_timing_mode=evaluation.timing_mode,
        )

    try:
        outcome = compare_observation(observation, sample)
    except Exception as error:
        if not options.keep_going:
            raise
        return SampleResult(
            case_name=sample.case_name,
            target_id=sample.target_id,
            target_label=sample.target_label,
            sample_index=sample.sample_index,
            timestamp_s=sample.timestamp_s,
            status="error",
            expected=sample.expected,
            observed=observation,
            observed_value=None,
            compare_mode=sample.compare.mode,
            field=sample.field,
            reason=f"comparison_error: {error}",
            source=sample.source,
            evaluation_duration_s=evaluation.duration_s,
            evaluation_timing_mode=evaluation.timing_mode,
        )
    return SampleResult(
        case_name=sample.case_name,
        target_id=sample.target_id,
        target_label=sample.target_label,
        sample_index=sample.sample_index,
        timestamp_s=sample.timestamp_s,
        status="passed" if outcome.passed else "failed",
        expected=sample.expected,
        observed=observation,
        observed_value=outcome.observed_value,
        compare_mode=outcome.mode,
        field=sample.field,
        reason=outcome.reason,
        source=sample.source,
        evaluation_duration_s=evaluation.duration_s,
        evaluation_timing_mode=evaluation.timing_mode,
    )


def _result_for_frame(
    evaluation: EvaluationOutcome,
    frame: FrameSample,
    *,
    options: RunOptions,
    eval_dir: Path,
    trial_index: int,
) -> SampleResult:
    result = _result_for_evaluation(evaluation, options=options)
    if result.status not in {"failed", "error"} or not options.save_failures:
        return result
    return _save_failure_artifacts(
        result,
        frame.image,
        options=options,
        eval_dir=eval_dir,
        trial_index=trial_index,
    )


def _save_failure_artifacts(
    result: SampleResult,
    image: Any,
    *,
    options: RunOptions,
    eval_dir: Path,
    trial_index: int,
) -> SampleResult:
    artifacts_dir = options.artifacts_dir or (eval_dir / "runs")
    failures_dir = artifacts_dir / "failures" / f"trial-{trial_index:03d}"
    stem = (
        f"{result.case_name}_{result.target_id}_"
        f"{result.sample_index:05d}_{result.timestamp_s:.3f}s"
    ).replace("/", "_")
    image_path = failures_dir / f"{stem}.jpg"
    json_path = failures_dir / f"{stem}.json"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(image_path, format="JPEG", quality=90)
    json_path.write_text(
        json.dumps(
            {"trial": trial_index, **_result_to_json(result)},
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return SampleResult(
        case_name=result.case_name,
        target_id=result.target_id,
        target_label=result.target_label,
        sample_index=result.sample_index,
        timestamp_s=result.timestamp_s,
        status=result.status,
        expected=result.expected,
        observed=result.observed,
        observed_value=result.observed_value,
        compare_mode=result.compare_mode,
        field=result.field,
        reason=result.reason,
        source=result.source,
        evaluation_duration_s=result.evaluation_duration_s,
        evaluation_timing_mode=result.evaluation_timing_mode,
        artifact_image=str(image_path),
        artifact_json=str(json_path),
    )


def _summarize_stability(
    trials: list[EvalTrialReport],
) -> list[SampleStability]:
    if not trials:
        raise RuntimeError("internal error: eval run completed without trials")
    reference_results = trials[0].results
    for trial in trials[1:]:
        if len(trial.results) != len(reference_results):
            raise RuntimeError(
                "internal error: repeated eval trials produced different result counts"
            )

    stability: list[SampleStability] = []
    for result_index, reference in enumerate(reference_results):
        repeated_results = [trial.results[result_index] for trial in trials]
        if any(
            _result_identity(result) != _result_identity(reference)
            for result in repeated_results[1:]
        ):
            raise RuntimeError(
                "internal error: repeated eval trials produced different sample order"
            )
        stability.append(
            SampleStability(
                case_name=reference.case_name,
                target_id=reference.target_id,
                target_label=reference.target_label,
                sample_index=reference.sample_index,
                timestamp_s=reference.timestamp_s,
                expected=reference.expected,
                source=reference.source,
                statuses=tuple(result.status for result in repeated_results),
            )
        )
    return stability


def _result_identity(result: SampleResult) -> tuple[str, str, int, float]:
    return (
        result.case_name,
        result.target_id,
        result.sample_index,
        result.timestamp_s,
    )


def _apply_stability_gates(
    stability: list[SampleStability], options: RunOptions
) -> list[GateResult]:
    if options.max_flaky_samples is None:
        return []
    flaky_count = sum(sample.flaky for sample in stability)
    threshold = options.max_flaky_samples
    sample_label = "sample" if flaky_count == 1 else "samples"
    return [
        GateResult(
            name="max_flaky_samples",
            passed=flaky_count <= threshold,
            message=f"{flaky_count} flaky {sample_label} (gate: <= {threshold})",
        )
    ]


def _apply_quality_gates(
    eval_directory: EvalDirectory, results: list[SampleResult], options: RunOptions
) -> list[GateResult]:
    results = [result for result in results if result.status != "ignored"]
    selected_target_ids = _selected_target_ids(options.target_filter)
    time_filtered = options.from_time_s is not None or options.until_time_s is not None
    sampled_target_ids = (
        {
            target.id
            for case in eval_directory.cases
            for target in case.targets
            if target.samples
        }
        if time_filtered
        else None
    )
    gates: list[GateResult] = []
    error_count = sum(1 for result in results if result.status == "error")
    gates.append(
        GateResult(
            name="adapter_errors",
            passed=error_count == 0,
            message=(
                "no adapter/comparison errors"
                if error_count == 0
                else f"{error_count} adapter/comparison errors"
            ),
        )
    )

    global_thresholds = eval_directory.thresholds
    min_pass_rate = _coalesce(options.min_pass_rate, global_thresholds.min_pass_rate)
    max_failures = _coalesce(options.max_failures, global_thresholds.max_failures)
    min_target_pass_rate = options.min_target_pass_rate

    if min_pass_rate is not None:
        gates.append(_pass_rate_gate("eval_min_pass_rate", results, min_pass_rate))
    if max_failures is not None:
        failure_count = sum(1 for result in results if result.status == "failed")
        gates.append(
            GateResult(
                name="eval_max_failures",
                passed=failure_count <= max_failures,
                message=f"{failure_count} failures (gate: <= {max_failures})",
            )
        )
    if min_target_pass_rate is not None:
        gates.extend(
            _target_pass_rate_gates(results, min_target_pass_rate, "all_targets")
        )
    else:
        gates.extend(
            _configured_target_pass_rate_gates(
                results,
                global_thresholds,
                "eval",
                selected_target_ids=selected_target_ids,
                sampled_target_ids=sampled_target_ids,
                fail_empty_targets=(
                    options.case_filter is None and selected_target_ids is None
                ),
            )
        )

    for case in eval_directory.cases:
        case_results = [result for result in results if result.case_name == case.name]
        gates.extend(_case_gates(case, case_results, options, selected_target_ids))
    return gates


def _case_gates(
    case: EvalCase,
    results: list[SampleResult],
    options: RunOptions,
    selected_target_ids: set[str] | None,
) -> list[GateResult]:
    if options.min_pass_rate is not None or options.max_failures is not None:
        return []
    case_name = case.name
    thresholds = case.thresholds
    declared_target_ids = {target.id for target in case.targets}
    sampled_target_ids = {target.id for target in case.targets if target.samples}
    time_filtered = options.from_time_s is not None or options.until_time_s is not None
    gates: list[GateResult] = []
    if thresholds.min_pass_rate is not None:
        gates.append(
            _pass_rate_gate(
                f"{case_name}_min_pass_rate", results, thresholds.min_pass_rate
            )
        )
    if thresholds.max_failures is not None:
        failure_count = sum(1 for result in results if result.status == "failed")
        gates.append(
            GateResult(
                name=f"{case_name}_max_failures",
                passed=failure_count <= thresholds.max_failures,
                message=(
                    f"{case_name}: {failure_count} failures "
                    f"(gate: <= {thresholds.max_failures})"
                ),
            )
        )
    for target_id, threshold in thresholds.per_target.items():
        if selected_target_ids is not None and target_id not in selected_target_ids:
            continue
        # Undeclared target ids still produce an empty, failing gate. Only suppress
        # targets known to have been emptied by the requested time window.
        if (
            time_filtered
            and target_id in declared_target_ids
            and target_id not in sampled_target_ids
        ):
            continue
        if threshold.min_pass_rate is None:
            continue
        target_results = [result for result in results if result.target_id == target_id]
        gates.append(
            _pass_rate_gate(
                f"{case_name}_{target_id}_min_pass_rate",
                target_results,
                threshold.min_pass_rate,
            )
        )
    return gates


def _target_pass_rate_gates(
    results: list[SampleResult], threshold: float, prefix: str
) -> list[GateResult]:
    grouped: dict[str, list[SampleResult]] = defaultdict(list)
    for result in results:
        grouped[result.target_id].append(result)
    return [
        _pass_rate_gate(
            f"{prefix}_{target_id}_min_pass_rate", target_results, threshold
        )
        for target_id, target_results in sorted(grouped.items())
    ]


def _configured_target_pass_rate_gates(
    results: list[SampleResult],
    thresholds: Thresholds,
    prefix: str,
    *,
    selected_target_ids: set[str] | None,
    sampled_target_ids: set[str] | None,
    fail_empty_targets: bool,
) -> list[GateResult]:
    gates: list[GateResult] = []
    for target_id, threshold in thresholds.per_target.items():
        if selected_target_ids is not None and target_id not in selected_target_ids:
            continue
        if sampled_target_ids is not None and target_id not in sampled_target_ids:
            continue
        if threshold.min_pass_rate is None:
            continue
        target_results = [result for result in results if result.target_id == target_id]
        if (
            not target_results
            and not fail_empty_targets
            and (selected_target_ids is None or target_id not in selected_target_ids)
        ):
            continue
        gates.append(
            _pass_rate_gate(
                f"{prefix}_{target_id}_min_pass_rate",
                target_results,
                threshold.min_pass_rate,
            )
        )
    return gates


def _selected_target_ids(
    target_filter: str | tuple[str, ...] | None,
) -> set[str] | None:
    if target_filter is None:
        return None
    if isinstance(target_filter, str):
        return {target_filter}
    return set(target_filter)


def _pass_rate_gate(
    name: str, results: list[SampleResult], threshold: float
) -> GateResult:
    pass_rate = _pass_rate(results)
    return GateResult(
        name=name,
        passed=bool(results) and pass_rate >= threshold,
        message=f"{pass_rate:.1%} pass rate (gate: >= {threshold:.1%})",
    )


def _pass_rate(results: list[SampleResult]) -> float:
    if not results:
        return 0.0
    return sum(1 for result in results if result.status == "passed") / len(results)


def _coalesce(primary: Any, fallback: Any) -> Any:
    return primary if primary is not None else fallback


def _report_to_json(report: EvalRunReport) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "report_type": "eval_run",
        "eval_dir": str(report.eval_dir),
        "cases": report.case_names,
        "repeat_count": report.repeat_count,
        "success": report.success,
        "checkpoint": (
            {
                "path": str(report.checkpoint_path),
                "resumed": report.resumed,
                "resumable_adapter_errors": report.resumable_error_count,
            }
            if report.checkpoint_path is not None
            else None
        ),
        "summary": {
            "trials": report.repeat_count,
            "successful_trials": report.successful_trial_count,
            "evaluated_samples": report.evaluated_sample_count,
            "ignored_samples": report.ignored_sample_count,
            "evaluated_attempts": report.evaluated_attempt_count,
            "passed_attempts": report.passed_attempt_count,
            "failed_attempts": report.failed_attempt_count,
            "error_attempts": report.error_attempt_count,
            "attempt_pass_rate": report.attempt_pass_rate,
            "minimum_trial_pass_rate": report.minimum_trial_pass_rate,
            "mean_trial_pass_rate": report.mean_trial_pass_rate,
            "maximum_trial_pass_rate": report.maximum_trial_pass_rate,
            "consistently_passed_samples": report.consistently_passed_sample_count,
            "consistently_failed_samples": report.consistently_failed_sample_count,
            "flaky_samples": report.flaky_sample_count,
            "error_samples": report.error_sample_count,
            "duration_seconds": report.duration_s,
            "evaluation_timing_mode": report.evaluation_timing_mode,
            "average_evaluation_seconds_per_attempt": (
                report.average_evaluation_duration_s
            ),
            "throughput_attempts_per_second": report.throughput_attempts_per_s,
        },
        "gates": [gate.__dict__ for gate in report.gate_results],
        "trials": [_trial_to_json(trial) for trial in report.trials],
        "stability": [_stability_to_json(sample) for sample in report.stability],
    }


def _trial_to_json(trial: EvalTrialReport) -> dict[str, Any]:
    return {
        "trial": trial.index,
        "success": trial.success,
        "summary": {
            "evaluated": trial.evaluated_count,
            "passed": trial.passed_count,
            "failed": trial.failed_count,
            "errors": trial.error_count,
            "ignored": trial.ignored_count,
            "pass_rate": trial.pass_rate,
            "duration_seconds": trial.duration_s,
            "evaluation_timing_mode": trial.evaluation_timing_mode,
            "average_evaluation_seconds_per_sample": (
                trial.average_evaluation_duration_s
            ),
            "throughput_samples_per_second": trial.throughput_samples_per_s,
        },
        "gates": [gate.__dict__ for gate in trial.gate_results],
        "results": [_result_to_json(result) for result in trial.results],
    }


def _stability_to_json(sample: SampleStability) -> dict[str, Any]:
    return {
        "case": sample.case_name,
        "target": sample.target_id,
        "target_label": sample.target_label,
        "sample_index": sample.sample_index,
        "timestamp_s": sample.timestamp_s,
        "expected": sample.expected,
        "source": sample.source,
        "statuses": list(sample.statuses),
        "evaluated": sample.evaluated_count,
        "passed": sample.passed_count,
        "failed": sample.failed_count,
        "errors": sample.error_count,
        "pass_rate": sample.pass_rate,
        "ignored": sample.ignored,
        "consistently_passed": sample.consistently_passed,
        "consistently_failed": sample.consistently_failed,
        "flaky": sample.flaky,
    }


def _result_to_json(result: SampleResult) -> dict[str, Any]:
    return {
        "case": result.case_name,
        "target": result.target_id,
        "target_label": result.target_label,
        "sample_index": result.sample_index,
        "timestamp_s": result.timestamp_s,
        "status": result.status,
        "expected": result.expected,
        "observed": result.observed,
        "observed_value": result.observed_value,
        "compare_mode": result.compare_mode,
        "field": result.field,
        "reason": result.reason,
        "source": result.source,
        "evaluation_duration_seconds": result.evaluation_duration_s,
        "evaluation_timing_mode": result.evaluation_timing_mode,
        "artifact_image": result.artifact_image,
        "artifact_json": result.artifact_json,
    }
