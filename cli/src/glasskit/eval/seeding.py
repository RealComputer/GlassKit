from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import yaml

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
    SampleExpectation,
    SeededExpectation,
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
    def on_case_start(self, case: EvalCase, sample_count: int) -> None: ...

    def on_target_start(
        self, case: EvalCase, target_id: str, sample_count: int
    ) -> None: ...

    def on_result(self, result: SeededExpectation) -> None: ...


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
    sources = {case.path: source_snapshot[case.path] for case in eval_directory.cases}
    for path, source in sources.items():
        if _read_text(path) != source.text:
            raise EvalConfigError(
                f"case changed while its draft was being loaded; retry seeding: {path}"
            )
    samples_to_seed = {
        (case.name, sample.sample_index): sample
        for case in eval_directory.cases
        for sample in case.samples
        if options.replace or not sample.has_expectation
    }
    preserved_count = sum(
        sample.has_expectation and not options.replace
        for case in eval_directory.cases
        for sample in case.samples
    )
    if not samples_to_seed:
        return SeedReport(
            eval_dir=eval_directory.path,
            case_names=[],
            seeded=[],
            preserved_count=preserved_count,
            duration_s=max(0.0, perf_counter() - started_at),
        )

    _validate_seed_videos(eval_directory.cases, samples_to_seed)
    evaluator = await load_configured_evaluator(
        options.adapter,
        options.adapter_command,
        AdapterConfig(
            eval_dir=eval_directory.path,
            config=options.adapter_config,
            verbose=options.verbose,
        ),
    )
    seeded: list[SeededExpectation] = []
    try:
        for case in eval_directory.cases:
            case_samples = [
                sample
                for sample in case.samples
                if (case.name, sample.sample_index) in samples_to_seed
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
                        if (case.name, sample.sample_index) in samples_to_seed
                    ]
                    if not target_samples:
                        continue
                    if callbacks is not None:
                        callbacks.on_target_start(case, target.id, len(target_samples))
                    context = TargetContext(
                        id=target.id,
                        index=target.index,
                        label=target.label,
                        config=target.config,
                    )
                    seeded.extend(
                        await evaluate_samples(
                            evaluator,
                            frame_cursor,
                            target_samples,
                            context,
                            concurrency=options.concurrency,
                            keep_going=False,
                            transform=lambda outcome, _frame: _seeded_expectation(
                                outcome, callbacks=callbacks
                            ),
                        )
                    )
            finally:
                frame_cursor.close()
    finally:
        await close_evaluator(evaluator)

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

    return SeedReport(
        eval_dir=eval_directory.path,
        case_names=updated_case_names,
        seeded=seeded,
        preserved_count=preserved_count,
        duration_s=max(0.0, perf_counter() - started_at),
        directory_sync_warnings=tuple(sync_warnings),
    )


def _seeded_expectation(
    outcome: EvaluationOutcome, *, callbacks: SeedCallbacks | None
) -> SeededExpectation:
    if outcome.runtime_error is not None:
        raise outcome.runtime_error
    expected, field_error = extract_observation_field(
        outcome.observation, outcome.sample.field
    )
    if field_error is not None:
        sample = outcome.sample
        raise AdapterRuntimeError(
            f"cannot seed {sample.case_name}/{sample.target_id} sample "
            f"{sample.sample_index} at {sample.timestamp_s:g}s: {field_error}"
        )
    result = SeededExpectation(
        sample=outcome.sample,
        expected=expected,
        evaluation_duration_s=outcome.duration_s,
        evaluation_timing_mode=outcome.timing_mode,
    )
    if callbacks is not None:
        callbacks.on_result(result)
    return result


def _validate_seed_videos(
    cases: list[EvalCase],
    samples_to_seed: Mapping[tuple[str, int], SampleExpectation],
) -> None:
    issues: list[str] = []
    for case in cases:
        selected = [
            sample
            for sample in case.samples
            if (case.name, sample.sample_index) in samples_to_seed
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
    review_samples: list[ReviewSample] = []
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
        sample_offset += len(timestamps)
    if sample_offset != len(target.samples):
        raise EvalConfigError(
            f"{case.path}: target {target.id!r} sample schedule changed while seeding"
        )
    return reconstruct_target(
        target.id,
        review_samples,
        default_every_s=raw_case.sampling.every_s,
    ).blocks


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
