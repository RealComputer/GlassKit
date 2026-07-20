from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol, cast

import yaml

from .checkpoints import (
    CheckpointStore,
    attach_checkpoint,
    checkpoint_plan_hash,
)
from .compare import extract_observation_field
from .execution import (
    EvaluationOutcome,
    FrameCursor,
    close_evaluator,
    evaluate_samples,
    load_configured_evaluator,
)
from .expectations import (
    discover_case_paths,
    expand_sample_timestamps,
    load_case,
    load_eval_directory,
)
from .models import (
    AdapterConfig,
    AdapterRuntimeError,
    CaseWriteError,
    EvalCase,
    EvalConfigError,
    EvaluationTimingMode,
    SampleExpectation,
    SeededExpectation,
    SeedIncompleteError,
    SeedOptions,
    SeedReport,
    TargetContext,
    TargetSpec,
)
from .review.models import ReviewSample, SampleCompare, SampleOrigin
from .review.serialization import (
    atomic_replace_text,
    compact_json,
    dump_case_file,
    expectation_type,
    reconstruct_target,
)
from .schemas import RawCaseFile, parse_case_file
from .video import iter_sample_frames, probe_video, validate_sample_times


class SeedCallbacks(Protocol):
    def on_checkpoint(self, path: Path) -> None: ...

    def on_case_start(self, case: EvalCase, sample_count: int) -> None: ...

    def on_target_start(
        self, case: EvalCase, target_id: str, sample_count: int
    ) -> None: ...

    def on_result(self, result: SeededExpectation) -> None: ...

    def on_error(self, sample: SampleExpectation, error: Exception) -> None: ...


@dataclass(frozen=True)
class _CaseSource:
    text: str
    mapping: dict[str, Any]
    raw: RawCaseFile


async def seed_eval(
    options: SeedOptions, callbacks: SeedCallbacks | None = None
) -> SeedReport:
    if options.adapter is not None and options.adapter_command is not None:
        raise EvalConfigError("adapter and adapter command are mutually exclusive")
    if options.adapter is None and options.adapter_command is None:
        raise EvalConfigError(
            "glasskit eval seed requires --adapter or --adapter-command"
        )
    if options.concurrency < 1:
        raise EvalConfigError("concurrency must be greater than 0")

    started_at = perf_counter()
    source_snapshot = {
        path: _read_case_source(path)
        for path in discover_case_paths(
            options.eval_dir,
            options.case_filter,
            target_filter=options.target_filter,
        )
    }
    eval_directory = load_eval_directory(
        options.eval_dir,
        case_filter=options.case_filter,
        target_filter=options.target_filter,
        allow_draft=True,
    )
    loaded_paths = {case.path for case in eval_directory.cases}
    snapshot_paths = set(source_snapshot)
    if loaded_paths != snapshot_paths:
        changed_paths = ", ".join(
            str(path) for path in sorted(loaded_paths ^ snapshot_paths)
        )
        raise EvalConfigError(
            "case selection changed while its draft was being loaded; retry "
            f"seeding: {changed_paths}"
        )
    sources = {case.path: source_snapshot[case.path] for case in eval_directory.cases}
    for path, source in sources.items():
        if _read_text(path) != source.text:
            raise EvalConfigError(
                f"case changed while its draft was being loaded; retry seeding: {path}"
            )
    samples_to_seed = {
        _sample_key(sample): sample
        for case in eval_directory.cases
        for sample in case.samples
        if options.replace or not sample.has_expectation
    }
    preserved_count = sum(
        sample.has_expectation and not options.replace
        for case in eval_directory.cases
        for sample in case.samples
    )
    if not samples_to_seed and options.resume_checkpoint is None:
        return SeedReport(
            eval_dir=eval_directory.path,
            case_names=[],
            seeded=[],
            preserved_count=preserved_count,
            duration_s=max(0.0, perf_counter() - started_at),
        )

    invocation = seed_checkpoint_invocation(options)
    plan_hash = checkpoint_plan_hash(eval_directory, invocation)
    checkpoint = (
        CheckpointStore.resume(
            eval_dir=eval_directory.path,
            reference=options.resume_checkpoint,
            kind="seed",
            plan_hash=plan_hash,
        )
        if options.resume_checkpoint is not None
        else CheckpointStore.create(
            kind="seed",
            eval_dir=eval_directory.path,
            invocation=invocation,
            plan_hash=plan_hash,
            total=len(samples_to_seed),
        )
    )
    discard_checkpoint = False
    try:
        saved = checkpoint.latest("seed_result")
        _validate_checkpoint_keys(saved, samples_to_seed, checkpoint.path)
        successful = {
            key: _seeded_from_checkpoint(samples_to_seed[key], payload)
            for key, payload in saved.items()
            if payload.get("status") == "success"
        }
        if successful:
            _publish_reusable_checkpoint(checkpoint, callbacks)
        pending = {
            key: sample
            for key, sample in samples_to_seed.items()
            if key not in successful
        }
        _validate_seed_videos(eval_directory.cases, pending)

        if pending:
            evaluator = await load_configured_evaluator(
                options.adapter,
                options.adapter_command,
                AdapterConfig(
                    eval_dir=eval_directory.path,
                    config=options.adapter_config,
                    verbose=options.verbose,
                ),
            )
            try:
                for case in eval_directory.cases:
                    case_samples = [
                        sample
                        for sample in case.samples
                        if _sample_key(sample) in pending
                    ]
                    if not case_samples:
                        continue
                    if callbacks is not None:
                        callbacks.on_case_start(case, len(case_samples))
                    frame_cursor = FrameCursor(
                        iter_sample_frames(
                            case.video_path,
                            case_samples,
                            case_name=case.name,
                        )
                    )
                    try:
                        for target in case.targets:
                            target_samples = [
                                sample
                                for sample in target.samples
                                if _sample_key(sample) in pending
                            ]
                            if not target_samples:
                                continue
                            if callbacks is not None:
                                callbacks.on_target_start(
                                    case, target.id, len(target_samples)
                                )
                            context = TargetContext(
                                id=target.id,
                                index=target.index,
                                label=target.label,
                                config=target.config,
                            )
                            await evaluate_samples(
                                evaluator,
                                frame_cursor,
                                target_samples,
                                context,
                                concurrency=options.concurrency,
                                keep_going=options.keep_going,
                                transform=lambda outcome, _frame: (
                                    _checkpoint_seed_outcome(
                                        outcome,
                                        checkpoint=checkpoint,
                                        keep_going=options.keep_going,
                                        callbacks=callbacks,
                                    )
                                ),
                            )
                    finally:
                        frame_cursor.close()
            finally:
                await close_evaluator(evaluator)

        saved = checkpoint.latest("seed_result")
        successful = {
            key: _seeded_from_checkpoint(samples_to_seed[key], payload)
            for key, payload in saved.items()
            if key in samples_to_seed and payload.get("status") == "success"
        }
        incomplete_count = len(samples_to_seed) - len(successful)
        if incomplete_count:
            expectation_label = (
                "expectation" if incomplete_count == 1 else "expectations"
            )
            raise SeedIncompleteError(
                f"{incomplete_count} {expectation_label} could not be seeded; "
                "the case YAML was not changed"
            )

        seeded = [
            successful[_sample_key(sample)]
            for case in eval_directory.cases
            for sample in case.samples
            if _sample_key(sample) in samples_to_seed
        ]
        seeded_by_case_index = {
            (result.sample.case_name, result.sample.sample_index): result
            for result in seeded
        }
        candidate_sources: dict[Path, str] = {}
        updated_case_names: list[str] = []
        for case in eval_directory.cases:
            case_results = {
                sample_index: result
                for (case_name, sample_index), result in seeded_by_case_index.items()
                if case_name == case.name
            }
            if not case_results:
                continue
            candidate_sources[case.path] = _build_seeded_case_source(
                case,
                source=sources[case.path],
                seeded=case_results,
            )
            updated_case_names.append(case.name)

        for path, source in sources.items():
            if path not in candidate_sources:
                continue
            if _read_text(path) != source.text:
                raise EvalConfigError(
                    f"case changed while expectations were being seeded; refusing to "
                    f"overwrite: {path}"
                )

        sync_warnings: list[Path] = []
        for path, candidate_source in candidate_sources.items():
            if _read_text(path) != sources[path].text:
                raise EvalConfigError(
                    f"case changed while expectations were being seeded; refusing to "
                    f"overwrite: {path}"
                )
            try:
                directory_sync_failed = atomic_replace_text(path, candidate_source)
            except OSError as error:
                raise CaseWriteError(
                    f"could not write seeded case file {path}: {error}"
                ) from error
            if directory_sync_failed:
                sync_warnings.append(path)

        checkpoint.mark_complete()
        return SeedReport(
            eval_dir=eval_directory.path,
            case_names=updated_case_names,
            seeded=seeded,
            preserved_count=preserved_count,
            duration_s=max(0.0, perf_counter() - started_at),
            directory_sync_warnings=tuple(sync_warnings),
        )
    except BaseException as error:
        if checkpoint.has_reusable_results:
            attach_checkpoint(error, checkpoint)
        else:
            discard_checkpoint = True
        raise
    finally:
        checkpoint.release()
        if discard_checkpoint:
            checkpoint.discard_if_no_reusable_results()


def seed_checkpoint_invocation(options: SeedOptions) -> dict[str, Any]:
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
        "adapter_config": dict(options.adapter_config),
        "concurrency": options.concurrency,
        "replace": options.replace,
        "keep_going": options.keep_going,
        "verbose": options.verbose,
    }


def seed_options_from_invocation(
    invocation: Mapping[str, Any],
    *,
    checkpoint_path: Path,
) -> SeedOptions:
    target_filter = invocation.get("target_filter")
    if isinstance(target_filter, list):
        target_filter = tuple(str(value) for value in target_filter)
    adapter_config = invocation.get("adapter_config", {})
    if not isinstance(adapter_config, Mapping):
        raise EvalConfigError("seed checkpoint adapter_config must be an object")
    return SeedOptions(
        eval_dir=Path(str(invocation.get("eval_dir", "eval"))),
        adapter=_optional_string(invocation.get("adapter")),
        adapter_command=_optional_string(invocation.get("adapter_command")),
        case_filter=_optional_string(invocation.get("case_filter")),
        target_filter=target_filter,
        adapter_config=dict(adapter_config),
        concurrency=int(invocation.get("concurrency", 1)),
        replace=invocation.get("replace") is True,
        keep_going=invocation.get("keep_going") is True,
        verbose=invocation.get("verbose") is True,
        resume_checkpoint=checkpoint_path,
    )


def _checkpoint_seed_outcome(
    outcome: EvaluationOutcome,
    *,
    checkpoint: CheckpointStore,
    keep_going: bool,
    callbacks: SeedCallbacks | None,
) -> SeededExpectation | bool:
    if outcome.runtime_error is not None:
        return _checkpoint_seed_error(
            outcome.sample,
            outcome.runtime_error,
            checkpoint=checkpoint,
            keep_going=keep_going,
            callbacks=callbacks,
        )
    expected, field_error = extract_observation_field(
        outcome.observation, outcome.sample.field
    )
    if field_error is not None:
        sample = outcome.sample
        error = AdapterRuntimeError(
            f"cannot seed {sample.case_name}/{sample.target_id} sample "
            f"{sample.sample_index} at {sample.timestamp_s:g}s: {field_error}"
        )
        return _checkpoint_seed_error(
            sample,
            error,
            checkpoint=checkpoint,
            keep_going=keep_going,
            callbacks=callbacks,
        )
    result = SeededExpectation(
        sample=outcome.sample,
        expected=expected,
        evaluation_duration_s=outcome.duration_s,
        evaluation_timing_mode=outcome.timing_mode,
    )
    checkpoint.record(
        "seed_result",
        _sample_key(outcome.sample),
        {
            "status": "success",
            "expected": expected,
            "evaluation_duration_seconds": outcome.duration_s,
            "evaluation_timing_mode": outcome.timing_mode,
        },
    )
    _publish_reusable_checkpoint(checkpoint, callbacks)
    if callbacks is not None:
        callbacks.on_result(result)
    return result


def _publish_reusable_checkpoint(
    checkpoint: CheckpointStore, callbacks: SeedCallbacks | None
) -> None:
    if not checkpoint.mark_reusable():
        return
    if callbacks is not None and callable(
        on_checkpoint := getattr(callbacks, "on_checkpoint", None)
    ):
        on_checkpoint(checkpoint.path)


def _checkpoint_seed_error(
    sample: SampleExpectation,
    error: Exception,
    *,
    checkpoint: CheckpointStore,
    keep_going: bool,
    callbacks: SeedCallbacks | None,
) -> bool:
    if not keep_going:
        raise error
    checkpoint.record(
        "seed_result",
        _sample_key(sample),
        {"status": "error", "message": str(error)},
    )
    if callbacks is not None and callable(
        on_error := getattr(callbacks, "on_error", None)
    ):
        on_error(sample, error)
    return False


def _seeded_from_checkpoint(
    sample: SampleExpectation, payload: Mapping[str, Any]
) -> SeededExpectation:
    duration = payload.get("evaluation_duration_seconds")
    timing_mode = payload.get("evaluation_timing_mode")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        raise EvalConfigError(
            "checkpoint contains an invalid seed evaluation duration for "
            f"{sample.case_name}/{sample.target_id} sample {sample.sample_index}"
        )
    if timing_mode not in {"individual", "batch_amortized"}:
        raise EvalConfigError(
            "checkpoint contains an invalid seed timing mode for "
            f"{sample.case_name}/{sample.target_id} sample {sample.sample_index}"
        )
    return SeededExpectation(
        sample=sample,
        expected=payload.get("expected"),
        evaluation_duration_s=float(duration),
        evaluation_timing_mode=cast(EvaluationTimingMode, timing_mode),
    )


def _validate_checkpoint_keys(
    saved: Mapping[str, Any],
    selected: Mapping[str, SampleExpectation],
    checkpoint_path: Path,
) -> None:
    unexpected = sorted(set(saved) - set(selected))
    if unexpected:
        raise EvalConfigError(
            f"checkpoint contains results outside the selected seed plan: "
            f"{checkpoint_path}"
        )


def _sample_key(sample: SampleExpectation) -> str:
    return (
        f"{sample.case_name}\u0000{sample.target_id}\u0000"
        f"{sample.sample_index}\u0000{float(sample.timestamp_s).hex()}"
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _validate_seed_videos(
    cases: list[EvalCase],
    samples_to_seed: Mapping[str, SampleExpectation],
) -> None:
    issues: list[str] = []
    for case in cases:
        selected = [
            sample for sample in case.samples if _sample_key(sample) in samples_to_seed
        ]
        if not selected:
            continue
        metadata = probe_video(case.video_path)
        issues.extend(validate_sample_times(selected, metadata))
    if issues:
        raise EvalConfigError("; ".join(issues))


def _read_case_source(path: Path) -> _CaseSource:
    text = _read_text(path)
    try:
        value = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError) as error:
        raise EvalConfigError(f"{path}: invalid YAML: {error}") from error
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise EvalConfigError(f"{path}: expected a YAML object")
    return _CaseSource(
        text=text,
        mapping=value,
        raw=parse_case_file(value, label=str(path)),
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise EvalConfigError(f"{path}: could not read file: {error}") from error


def _build_seeded_case_source(
    case: EvalCase,
    *,
    source: _CaseSource,
    seeded: Mapping[int, SeededExpectation],
) -> str:
    raw_targets = source.mapping.get("targets")
    if not isinstance(raw_targets, Mapping):
        raise EvalConfigError(f"{case.path}: targets must be an object")
    candidate = dict(source.mapping)
    candidate_targets = dict(raw_targets)
    candidate["targets"] = candidate_targets

    for target in case.targets:
        if not any(sample.sample_index in seeded for sample in target.samples):
            continue
        raw_target_mapping = candidate_targets.get(target.id)
        if not isinstance(raw_target_mapping, Mapping):
            raise EvalConfigError(
                f"{case.path}: target {target.id!r} changed while seeding"
            )
        replacement_target = dict(raw_target_mapping)
        replacement_target["samples"] = _reconstruct_seeded_target(
            case,
            target,
            raw_case=source.raw,
            seeded=seeded,
        )
        candidate_targets[target.id] = replacement_target

    rendered = dump_case_file(candidate)
    _validate_candidate_case(case.path, rendered)
    return rendered


def _reconstruct_seeded_target(
    case: EvalCase,
    target: TargetSpec,
    *,
    raw_case: RawCaseFile,
    seeded: Mapping[int, SeededExpectation],
) -> list[dict[str, Any]]:
    raw_target = raw_case.targets[target.id]
    reconstructed_blocks: list[dict[str, Any]] = []
    sample_offset = 0
    for block_index, raw_block in enumerate(raw_target.samples, start=1):
        timestamps = expand_sample_timestamps(
            raw_block,
            default_every_s=raw_case.sampling.every_s,
            case_path=case.path,
            target_id=target.id,
            block_index=block_index,
        )
        block_samples = target.samples[sample_offset : sample_offset + len(timestamps)]
        if [sample.timestamp_s for sample in block_samples] != timestamps:
            raise EvalConfigError(
                f"{case.path}: target {target.id!r} sample schedule changed while "
                "seeding"
            )
        kind = "range" if raw_block.range_ is not None else "at"
        effective_every = (
            raw_block.every_s
            if raw_block.every_s is not None
            else raw_case.sampling.every_s
        )
        review_samples: list[ReviewSample] = []
        for sample in block_samples:
            generated = seeded.get(sample.sample_index)
            if generated is None and not sample.has_expectation:
                raise RuntimeError(
                    "internal error: seeding left a selected expectation missing"
                )
            expected = generated.expected if generated is not None else sample.expected
            review_samples.append(
                ReviewSample(
                    id=f"seed-{sample.sample_index}",
                    timestamp_s=sample.timestamp_s,
                    expect_type=expectation_type(expected),
                    expect_json=compact_json(expected),
                    field=sample.field,
                    compare=SampleCompare(
                        mode=sample.compare.mode,
                        tolerance=sample.compare.tolerance,
                    ),
                    comment=sample.comment,
                    ignore=sample.ignore,
                    origin=SampleOrigin(
                        block_index=block_index,
                        kind=kind,
                        every_s=effective_every if kind == "range" else None,
                    ),
                )
            )
        reconstructed_blocks.extend(
            reconstruct_target(
                target.id,
                review_samples,
                default_every_s=raw_case.sampling.every_s,
                sample_defaults=target.sample_defaults,
                range_end_bound_s=(
                    raw_block.range_[1] if raw_block.range_ is not None else None
                ),
                allow_range_reconstruction=raw_block.range_ is not None,
            ).blocks
        )
        sample_offset += len(timestamps)
    if sample_offset != len(target.samples):
        raise EvalConfigError(
            f"{case.path}: target {target.id!r} sample schedule changed while seeding"
        )
    return reconstructed_blocks


def _validate_candidate_case(path: Path, source: str) -> None:
    try:
        value = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise RuntimeError(
            "internal error: seeded case rendered invalid YAML"
        ) from error
    raw_case = parse_case_file(value, label=str(path))
    loaded = load_case(path, raw_case=raw_case, allow_draft=True)
    metadata = probe_video(loaded.video_path)
    issues = validate_sample_times(loaded.samples, metadata)
    if issues:
        raise EvalConfigError("; ".join(issues))
