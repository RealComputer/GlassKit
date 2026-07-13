from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from .adapters import LoadedEvaluator, load_evaluator
from .compare import compare_observation
from .expectations import load_eval_directory
from .json_values import json_value_error
from .models import (
    AdapterConfig,
    AdapterRuntimeError,
    EvalCase,
    EvalConfigError,
    EvalDirectory,
    EvalRunReport,
    EvaluationTimingMode,
    FrameSample,
    GateResult,
    RunOptions,
    SampleExpectation,
    SampleResult,
    TargetContext,
    Thresholds,
    ValidationIssue,
    ValidationReport,
)
from .video import decode_sample_frames, probe_video, validate_sample_times


class RunCallbacks(Protocol):
    def on_case_start(self, case: EvalCase, sample_count: int) -> None: ...

    def on_target_start(
        self, case: EvalCase, target_id: str, sample_count: int
    ) -> None: ...

    def on_result(self, result: SampleResult) -> None: ...


@dataclass(frozen=True)
class _EvaluationOutcome:
    sample: SampleExpectation
    observation: Any
    runtime_error: Exception | None
    duration_s: float
    timing_mode: EvaluationTimingMode


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
    if options.adapter is not None:
        try:
            evaluator = await load_evaluator(
                options.adapter,
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
    if options.adapter is None:
        raise EvalConfigError("glasskit eval run requires --adapter")
    if options.concurrency < 1:
        raise EvalConfigError("concurrency must be greater than 0")
    started_at = perf_counter()
    eval_directory = load_eval_directory(
        options.eval_dir,
        case_filter=options.case_filter,
        target_filter=options.target_filter,
        allow_empty=options.allow_empty,
    )
    validation_issues = _validate_videos(eval_directory)
    error_messages = [
        issue.message for issue in validation_issues if issue.severity == "error"
    ]
    if error_messages:
        raise EvalConfigError("; ".join(error_messages))

    evaluator = await load_evaluator(
        options.adapter,
        AdapterConfig(
            eval_dir=eval_directory.path,
            config=options.adapter_config,
            artifacts_dir=options.artifacts_dir,
            verbose=options.verbose,
        ),
    )

    results: list[SampleResult] = []
    try:
        for case in eval_directory.cases:
            case_samples = case.samples
            evaluated_case_samples = [
                sample for sample in case_samples if sample.ignore is None
            ]
            if callbacks is not None:
                callbacks.on_case_start(case, len(case_samples))
            decoded = decode_sample_frames(
                case.video_path,
                evaluated_case_samples,
                case_name=case.name,
            )
            for target in case.targets:
                target_samples = target.samples
                if callbacks is not None:
                    callbacks.on_target_start(case, target.id, len(target_samples))
                context = TargetContext(
                    id=target.id,
                    index=target.index,
                    label=target.label,
                    config=target.config,
                )
                evaluated_target_samples = [
                    sample for sample in target_samples if sample.ignore is None
                ]
                frames = [
                    decoded[sample.sample_index] for sample in evaluated_target_samples
                ]
                evaluations = await _evaluate_samples(
                    evaluator,
                    frames,
                    evaluated_target_samples,
                    context,
                    options=options,
                )
                evaluated_results = {
                    evaluation.sample.sample_index: _result_for_evaluation(
                        evaluation, options=options
                    )
                    for evaluation in evaluations
                }
                for sample in target_samples:
                    result = (
                        _ignored_result(sample)
                        if sample.ignore is not None
                        else evaluated_results[sample.sample_index]
                    )
                    if result.status in {"failed", "error"} and options.save_failures:
                        frame = decoded.get(sample.sample_index)
                        if frame is not None:
                            result = _save_failure_artifacts(
                                result,
                                frame.image,
                                options=options,
                                eval_dir=eval_directory.path,
                            )
                    results.append(result)
                    if callbacks is not None:
                        callbacks.on_result(result)
    finally:
        await _close_evaluator(evaluator)

    gate_results = _apply_quality_gates(eval_directory, results, options)
    report = EvalRunReport(
        eval_dir=eval_directory.path,
        case_names=[case.name for case in eval_directory.cases],
        results=results,
        gate_results=gate_results,
        duration_s=max(0.0, perf_counter() - started_at),
    )
    if options.output_json is not None:
        write_json_report(report, options.output_json)
    return report


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


async def _evaluate_samples(
    evaluator: LoadedEvaluator,
    frames: list[FrameSample],
    samples: list[SampleExpectation],
    target: TargetContext,
    *,
    options: RunOptions,
) -> list[_EvaluationOutcome]:
    if not samples:
        return []
    if evaluator.supports_batch_evaluation:
        return await _evaluate_sample_batch(
            evaluator,
            frames,
            samples,
            target,
            options=options,
        )
    return await _evaluate_samples_individually(
        evaluator,
        frames,
        samples,
        target,
        options=options,
    )


async def _evaluate_sample_batch(
    evaluator: LoadedEvaluator,
    frames: list[FrameSample],
    samples: list[SampleExpectation],
    target: TargetContext,
    *,
    options: RunOptions,
) -> list[_EvaluationOutcome]:
    started_at = perf_counter()
    try:
        observation_items = list(await evaluator.evaluate_many(frames, target))
        if len(observation_items) != len(samples):
            raise AdapterRuntimeError(
                f"adapter returned {len(observation_items)} observations for "
                f"{len(samples)} samples in target {target.id!r}"
            )
    except Exception as error:
        duration_s = _elapsed_seconds(started_at)
        runtime_error = _batch_adapter_runtime_error(error, target)
        if not options.keep_going:
            if runtime_error is error:
                raise runtime_error from None
            raise runtime_error from error
        amortized_duration_s = duration_s / len(samples)
        return [
            _EvaluationOutcome(
                sample=sample,
                observation=None,
                runtime_error=runtime_error,
                duration_s=amortized_duration_s,
                timing_mode="batch_amortized",
            )
            for sample in samples
        ]

    amortized_duration_s = _elapsed_seconds(started_at) / len(samples)
    results: list[_EvaluationOutcome] = []
    for sample, observation in zip(samples, observation_items, strict=True):
        results.append(
            _validated_observation(
                sample,
                observation,
                duration_s=amortized_duration_s,
                timing_mode="batch_amortized",
                keep_going=options.keep_going,
            )
        )
    return results


async def _evaluate_samples_individually(
    evaluator: LoadedEvaluator,
    frames: list[FrameSample],
    samples: list[SampleExpectation],
    target: TargetContext,
    *,
    options: RunOptions,
) -> list[_EvaluationOutcome]:
    async def evaluate_index(index: int) -> _EvaluationOutcome:
        sample = samples[index]
        started_at = perf_counter()
        try:
            observation = await evaluator.evaluate(frames[index], target)
        except Exception as error:
            duration_s = _elapsed_seconds(started_at)
            runtime_error = _sample_adapter_runtime_error(error, sample)
            if not options.keep_going:
                if runtime_error is error:
                    raise runtime_error from None
                raise runtime_error from error
            return _EvaluationOutcome(
                sample=sample,
                observation=None,
                runtime_error=runtime_error,
                duration_s=duration_s,
                timing_mode="individual",
            )
        return _validated_observation(
            sample,
            observation,
            duration_s=_elapsed_seconds(started_at),
            timing_mode="individual",
            keep_going=options.keep_going,
        )

    return await _bounded_map(
        len(samples),
        concurrency=options.concurrency,
        evaluate_index=evaluate_index,
    )


async def _bounded_map(
    item_count: int,
    *,
    concurrency: int,
    evaluate_index: Callable[[int], Awaitable[_EvaluationOutcome]],
) -> list[_EvaluationOutcome]:
    results: list[_EvaluationOutcome | None] = [None] * item_count
    next_index = 0
    stopped = False
    errors: list[tuple[int, Exception]] = []

    async def worker() -> None:
        nonlocal next_index, stopped
        while not stopped:
            index = next_index
            if index >= item_count:
                return
            next_index += 1
            try:
                results[index] = await evaluate_index(index)
            except Exception as error:
                errors.append((index, error))
                stopped = True

    workers = [
        asyncio.create_task(worker()) for _ in range(min(concurrency, item_count))
    ]
    try:
        await asyncio.gather(*workers)
    except asyncio.CancelledError as cancellation:
        for worker_task in workers:
            worker_task.cancel()
        for note in await _drain_workers(workers):
            cancellation.add_note(note)
        raise
    if errors:
        _, error = min(errors, key=lambda item: item[0])
        raise error
    if any(result is None for result in results):
        raise RuntimeError("internal error: concurrent evaluation left missing results")
    return [result for result in results if result is not None]


async def _drain_workers(workers: list[asyncio.Task[None]]) -> list[str]:
    pending = asyncio.gather(*workers, return_exceptions=True)
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            continue
    pending.result()
    notes: list[str] = []
    for worker in workers:
        try:
            worker.result()
        except asyncio.CancelledError as cancellation:
            notes.extend(getattr(cancellation, "__notes__", ()))
        except BaseException as error:
            notes.append(
                f"evaluation worker failed while draining cancellation: {error}"
            )
    return notes


def _validated_observation(
    sample: SampleExpectation,
    observation: Any,
    *,
    duration_s: float,
    timing_mode: EvaluationTimingMode,
    keep_going: bool,
) -> _EvaluationOutcome:
    if error_message := json_value_error(observation, label="observation"):
        error = AdapterRuntimeError(
            "adapter returned non-JSON observation for "
            f"{sample.case_name}/{sample.target_id} sample "
            f"{sample.sample_index}: {error_message}"
        )
        if not keep_going:
            raise error
        return _EvaluationOutcome(
            sample=sample,
            observation=None,
            runtime_error=error,
            duration_s=duration_s,
            timing_mode=timing_mode,
        )
    return _EvaluationOutcome(
        sample=sample,
        observation=observation,
        runtime_error=None,
        duration_s=duration_s,
        timing_mode=timing_mode,
    )


def _elapsed_seconds(started_at: float) -> float:
    return max(0.0, perf_counter() - started_at)


def _batch_adapter_runtime_error(error: Exception, target: TargetContext) -> Exception:
    if isinstance(error, AdapterRuntimeError):
        return error
    return AdapterRuntimeError(f"adapter failed for target {target.id!r}: {error}")


def _sample_adapter_runtime_error(
    error: Exception, sample: SampleExpectation
) -> Exception:
    if isinstance(error, AdapterRuntimeError):
        return error
    return AdapterRuntimeError(
        "adapter failed for "
        f"{sample.case_name}/{sample.target_id} sample {sample.sample_index} "
        f"at {sample.timestamp_s:g}s: {error}"
    )


async def _close_evaluator(evaluator: LoadedEvaluator) -> None:
    active_error = sys.exc_info()[1]
    try:
        await evaluator.close()
    except Exception as close_error:
        if active_error is not None:
            active_error.add_note(
                f"adapter close failed while handling previous error: {close_error}"
            )
            return
        raise AdapterRuntimeError(
            f"adapter close failed: {close_error}"
        ) from close_error


def _result_for_evaluation(
    evaluation: _EvaluationOutcome, *, options: RunOptions
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


def _save_failure_artifacts(
    result: SampleResult,
    image: Any,
    *,
    options: RunOptions,
    eval_dir: Path,
) -> SampleResult:
    artifacts_dir = options.artifacts_dir or (eval_dir / "runs")
    failures_dir = artifacts_dir / "failures"
    stem = (
        f"{result.case_name}_{result.target_id}_"
        f"{result.sample_index:05d}_{result.timestamp_s:.3f}s"
    ).replace("/", "_")
    image_path = failures_dir / f"{stem}.jpg"
    json_path = failures_dir / f"{stem}.json"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(image_path, format="JPEG", quality=90)
    json_path.write_text(
        json.dumps(_result_to_json(result), ensure_ascii=True, indent=2, sort_keys=True)
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


def _apply_quality_gates(
    eval_directory: EvalDirectory, results: list[SampleResult], options: RunOptions
) -> list[GateResult]:
    results = [result for result in results if result.status != "ignored"]
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
                selected_target=options.target_filter,
                fail_empty_targets=(
                    options.case_filter is None and options.target_filter is None
                ),
            )
        )

    for case in eval_directory.cases:
        case_results = [result for result in results if result.case_name == case.name]
        gates.extend(_case_gates(case.name, case.thresholds, case_results, options))
    return gates


def _case_gates(
    case_name: str,
    thresholds: Thresholds,
    results: list[SampleResult],
    options: RunOptions,
) -> list[GateResult]:
    if options.min_pass_rate is not None or options.max_failures is not None:
        return []
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
        if options.target_filter is not None and target_id != options.target_filter:
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
    selected_target: str | None,
    fail_empty_targets: bool,
) -> list[GateResult]:
    gates: list[GateResult] = []
    for target_id, threshold in thresholds.per_target.items():
        if selected_target is not None and target_id != selected_target:
            continue
        if threshold.min_pass_rate is None:
            continue
        target_results = [result for result in results if result.target_id == target_id]
        if (
            not target_results
            and not fail_empty_targets
            and target_id != selected_target
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
        "eval_dir": str(report.eval_dir),
        "cases": report.case_names,
        "success": report.success,
        "summary": {
            "evaluated": report.evaluated_count,
            "passed": report.passed_count,
            "failed": report.failed_count,
            "errors": report.error_count,
            "ignored": report.ignored_count,
            "pass_rate": report.pass_rate,
            "duration_seconds": report.duration_s,
            "evaluation_timing_mode": report.evaluation_timing_mode,
            "average_evaluation_seconds_per_sample": (
                report.average_evaluation_duration_s
            ),
            "throughput_samples_per_second": report.throughput_samples_per_s,
        },
        "gates": [gate.__dict__ for gate in report.gate_results],
        "results": [_result_to_json(result) for result in report.results],
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
