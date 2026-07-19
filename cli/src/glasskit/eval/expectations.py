from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .models import (
    ComparisonConfig,
    EvalCase,
    EvalConfigError,
    EvalDirectory,
    SampleExpectation,
    TargetSpec,
    TargetThreshold,
    Thresholds,
)
from .schemas import (
    RawCaseFile,
    RawCompare,
    RawSampleBlock,
    RawThresholds,
    parse_case_file,
    parse_eval_config_file,
    workflow_target_metadata,
)

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
YAML_SUFFIXES = (".yaml", ".yml")
EVAL_CONFIG_FILE_NAMES = ("config.yaml", "config.yml")
CASES_DIR_NAME = "cases"
MAX_EXPANDED_SAMPLES_PER_CASE = 10_000
_NANOSECONDS_PER_SECOND = 1_000_000_000
_EPSILON = 1e-9


def load_eval_directory(
    eval_dir: Path,
    *,
    case_filter: str | None = None,
    target_filter: str | Sequence[str] | None = None,
    from_time_s: float | None = None,
    until_time_s: float | None = None,
    allow_empty: bool = False,
) -> EvalDirectory:
    _validate_time_window(
        case_filter=case_filter,
        from_time_s=from_time_s,
        until_time_s=until_time_s,
    )
    eval_dir = _resolve_eval_dir(eval_dir)
    thresholds = _load_eval_thresholds(eval_dir)
    case_paths = discover_case_paths(eval_dir, case_filter)
    target_ids = (
        normalize_target_filters(target_filter) if target_filter is not None else None
    )
    if target_ids is not None:
        case_paths = _filter_case_paths_by_targets(case_paths, target_ids)
    cases = [load_case(case_path, allow_empty=allow_empty) for case_path in case_paths]
    if target_ids is not None:
        cases = _filter_cases_by_targets(cases, target_ids)
    if from_time_s is not None or until_time_s is not None:
        cases = _filter_cases_by_time(
            cases,
            from_time_s=from_time_s,
            until_time_s=until_time_s,
        )
        if not any(case.samples for case in cases):
            window = _format_time_window(from_time_s, until_time_s)
            raise EvalConfigError(f"no eval samples found {window}")
    if not allow_empty and not any(case.samples for case in cases):
        raise EvalConfigError("eval has no declared samples")
    return EvalDirectory(path=eval_dir, cases=cases, thresholds=thresholds)


def format_sample_schedule(eval_directory: EvalDirectory) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in eval_directory.cases:
        for target in case.targets:
            for sample in target.samples:
                rows.append(
                    {
                        "case": case.name,
                        "video": str(case.video_path),
                        "target": target.id,
                        "target_label": target.label,
                        "timestamp_s": sample.timestamp_s,
                        "expected": sample.expected,
                        "field": sample.field,
                        "mode": sample.compare.mode,
                        "ignore": sample.ignore,
                        "source": sample.source,
                    }
                )
    return rows


def _resolve_eval_dir(eval_dir: Path) -> Path:
    eval_dir = eval_dir.expanduser().resolve()
    if not eval_dir.exists():
        raise EvalConfigError(f"eval directory does not exist: {eval_dir}")
    if not eval_dir.is_dir():
        raise EvalConfigError(f"eval directory must be a directory: {eval_dir}")
    return eval_dir


def _load_eval_thresholds(eval_dir: Path) -> Thresholds:
    paths = [
        child
        for child in eval_dir.iterdir()
        if child.is_file() and child.name in EVAL_CONFIG_FILE_NAMES
    ]
    if not paths:
        return Thresholds()
    if len(paths) > 1:
        names = ", ".join(path.name for path in paths)
        raise EvalConfigError(f"multiple eval config files found: {names}; keep one")
    path = paths[0]
    raw = parse_eval_config_file(load_yaml_mapping(path), label=str(path))
    return _thresholds_from_raw(raw.thresholds)


def discover_case_paths(eval_dir: Path, case_filter: str | None = None) -> list[Path]:
    """Discover unambiguous case files using the normal eval path rules."""
    eval_dir = _resolve_eval_dir(eval_dir)
    cases_dir = eval_dir / CASES_DIR_NAME
    if not cases_dir.exists():
        raise EvalConfigError(f"cases directory does not exist: {cases_dir}")
    if not cases_dir.is_dir():
        raise EvalConfigError(f"cases path must be a directory: {cases_dir}")

    discovered = sorted(
        child
        for child in cases_dir.iterdir()
        if child.is_file() and child.suffix in YAML_SUFFIXES
    )
    if case_filter is not None:
        case_name = normalize_case_filter(case_filter)
        candidates = [path for path in discovered if path.stem == case_name]
    else:
        candidates = discovered
    if not candidates:
        suffix = f" matching case {case_filter!r}" if case_filter else ""
        raise EvalConfigError(f"no case files found under {cases_dir}{suffix}")
    _validate_unique_case_stems(candidates)
    return candidates


def _validate_unique_case_stems(case_paths: list[Path]) -> None:
    by_stem: dict[str, list[Path]] = {}
    for path in case_paths:
        by_stem.setdefault(path.stem, []).append(path)
    duplicates = {stem: paths for stem, paths in by_stem.items() if len(paths) > 1}
    if duplicates:
        details = "; ".join(
            f"{stem!r}: {', '.join(path.name for path in paths)}"
            for stem, paths in sorted(duplicates.items())
        )
        raise EvalConfigError(f"multiple case files share a name: {details}")


def normalize_case_filter(case_filter: str) -> str:
    _validate_case_filter(case_filter)
    path = Path(case_filter)
    if path.suffix in YAML_SUFFIXES:
        return path.stem
    return case_filter


def _validate_case_filter(case_filter: str) -> None:
    if (
        not case_filter
        or case_filter in {".", ".."}
        or Path(case_filter).name != case_filter
    ):
        raise EvalConfigError("case must be a filename or stem under cases/")


def normalize_target_filter(target_filter: str) -> str:
    if not target_filter or target_filter != target_filter.strip():
        raise EvalConfigError("target must be a target id from a case file")
    return target_filter


def normalize_target_filters(target_filter: str | Sequence[str]) -> tuple[str, ...]:
    target_ids = (target_filter,) if isinstance(target_filter, str) else target_filter
    if not target_ids:
        raise EvalConfigError("at least one target id must be provided")
    return tuple(
        dict.fromkeys(normalize_target_filter(target_id) for target_id in target_ids)
    )


def _filter_case_paths_by_targets(
    case_paths: list[Path], target_ids: tuple[str, ...]
) -> list[Path]:
    declared_by_path = {
        case_path: _case_file_target_ids(case_path) for case_path in case_paths
    }
    declared_target_ids = {
        target_id
        for case_target_ids in declared_by_path.values()
        for target_id in case_target_ids
    }
    missing_target_ids = [
        target_id for target_id in target_ids if target_id not in declared_target_ids
    ]
    if missing_target_ids:
        missing = ", ".join(repr(target_id) for target_id in missing_target_ids)
        available = ", ".join(
            repr(target_id) for target_id in sorted(declared_target_ids)
        )
        label = "target" if len(missing_target_ids) == 1 else "targets"
        raise EvalConfigError(
            f"requested eval {label} not found in the selected cases: {missing}; "
            f"available targets: {available or 'none'}"
        )

    selected_target_ids = set(target_ids)
    return [
        case_path
        for case_path, case_target_ids in declared_by_path.items()
        if selected_target_ids.intersection(case_target_ids)
    ]


def _case_file_target_ids(case_path: Path) -> set[str]:
    raw_targets = load_yaml_mapping(case_path).get("targets")
    if not isinstance(raw_targets, Mapping):
        return set()
    return {target_id for target_id in raw_targets if isinstance(target_id, str)}


def _filter_cases_by_targets(
    cases: list[EvalCase], target_ids: tuple[str, ...]
) -> list[EvalCase]:
    selected_target_ids = set(target_ids)
    filtered: list[EvalCase] = []
    for case in cases:
        targets = [
            target for target in case.targets if target.id in selected_target_ids
        ]
        if not targets:
            continue
        filtered.append(
            EvalCase(
                name=case.name,
                path=case.path,
                video_path=case.video_path,
                description=case.description,
                targets=targets,
                thresholds=case.thresholds,
            )
        )
    return filtered


def _validate_time_window(
    *,
    case_filter: str | None,
    from_time_s: float | None,
    until_time_s: float | None,
) -> None:
    if from_time_s is None and until_time_s is None:
        return
    if case_filter is None:
        raise EvalConfigError("--from and --until require --case")
    for option, value in (("--from", from_time_s), ("--until", until_time_s)):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise EvalConfigError(f"{option} must be a finite, nonnegative number")
    if (
        from_time_s is not None
        and until_time_s is not None
        and from_time_s >= until_time_s
    ):
        raise EvalConfigError("--from must be less than --until")


def _filter_cases_by_time(
    cases: list[EvalCase],
    *,
    from_time_s: float | None,
    until_time_s: float | None,
) -> list[EvalCase]:
    filtered_cases: list[EvalCase] = []
    for case in cases:
        filtered_targets: list[TargetSpec] = []
        for target in case.targets:
            samples = [
                sample
                for sample in target.samples
                if (from_time_s is None or sample.timestamp_s >= from_time_s)
                and (until_time_s is None or sample.timestamp_s < until_time_s)
            ]
            # Retain declared targets so gate evaluation can distinguish a target
            # removed by this window from a misspelled threshold target id.
            filtered_targets.append(
                TargetSpec(
                    id=target.id,
                    index=target.index,
                    label=target.label,
                    config=target.config,
                    samples=samples,
                )
            )
        if not any(target.samples for target in filtered_targets):
            continue
        filtered_cases.append(
            EvalCase(
                name=case.name,
                path=case.path,
                video_path=case.video_path,
                description=case.description,
                targets=filtered_targets,
                thresholds=case.thresholds,
            )
        )
    return filtered_cases


def _format_time_window(from_time_s: float | None, until_time_s: float | None) -> str:
    if from_time_s is not None and until_time_s is not None:
        return f"in time window [{from_time_s:g}, {until_time_s:g}) seconds"
    if from_time_s is not None:
        return f"at or after {from_time_s:g} seconds"
    if until_time_s is None:
        raise ValueError("time window requires at least one bound")
    return f"before {until_time_s:g} seconds"


def load_case(
    case_path: Path,
    *,
    allow_empty: bool = False,
    raw_case: RawCaseFile | None = None,
    resolve_video: bool = True,
) -> EvalCase:
    """Load one case, optionally expanding an already-parsed in-memory candidate.

    ``case_path`` remains the logical source path when ``raw_case`` is supplied, so
    relative video paths and user-facing errors behave exactly like an on-disk load.
    Review callers may disable video validation to retain normalized targets while
    separately reporting a missing, unsupported, or otherwise unusable video.
    """
    raw = raw_case
    if raw is None:
        raw = parse_case_file(load_yaml_mapping(case_path), label=str(case_path))

    video_path = (
        resolve_video_path(case_path, raw.video)
        if resolve_video
        else _logical_video_path(case_path, raw.video)
    )
    _preflight_case_expansion(raw, case_path=case_path)
    workflow_targets = {
        target.id: workflow_target_metadata(target) for target in raw.workflow.targets
    }

    targets: list[TargetSpec] = []
    next_sample_index = 0
    for target_index, (target_id, raw_target) in enumerate(raw.targets.items()):
        metadata = workflow_targets.get(target_id, {})
        label = raw_target.label or _optional_string(metadata.get("label"))
        target_config = _target_config(metadata, raw_target.config)

        samples: list[SampleExpectation] = []
        intervals: list[tuple[float, float, str]] = []
        for block_index, raw_block in enumerate(raw_target.samples, start=1):
            block_samples = _expand_sample_block(
                raw_block,
                case_name=case_path.stem,
                target_id=target_id,
                target_index=target_index,
                target_label=label,
                target_config=target_config,
                video_path=video_path,
                default_every_s=raw.sampling.every_s,
                next_sample_index=next_sample_index,
                block_index=block_index,
                case_path=case_path,
                intervals=intervals,
            )
            samples.extend(block_samples)
            next_sample_index += len(block_samples)

        _validate_target_normalized_timestamps(
            samples,
            case_path=case_path,
            target_id=target_id,
        )
        if not allow_empty and not samples:
            raise EvalConfigError(f"{case_path}: target {target_id!r} has no samples")
        targets.append(
            TargetSpec(
                id=target_id,
                index=target_index,
                label=label,
                config=target_config,
                samples=samples,
            )
        )

    if not allow_empty and not any(target.samples for target in targets):
        raise EvalConfigError(f"{case_path}: case has no samples")

    return EvalCase(
        name=case_path.stem,
        path=case_path,
        video_path=video_path,
        description=raw.description,
        targets=targets,
        thresholds=_thresholds_from_raw(raw.thresholds),
    )


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file and require an object at its top level."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise EvalConfigError(f"{path}: invalid YAML: {error}") from error
    except OSError as error:
        raise EvalConfigError(f"{path}: could not read file: {error}") from error
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise EvalConfigError(f"{path}: expected a YAML object")
    return raw


def resolve_video_path(case_path: Path, raw_video: Any) -> Path:
    """Resolve and validate a case video using normal eval rules."""
    path = _logical_video_path(case_path, raw_video)
    if not path.exists():
        raise EvalConfigError(f"video file does not exist: {path}")
    if not path.is_file():
        raise EvalConfigError(f"video path is not a file: {path}")
    if path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_VIDEO_SUFFIXES))
        raise EvalConfigError(
            f"unsupported video file type for {path}; supported suffixes: {supported}"
        )
    return path


def _logical_video_path(case_path: Path, raw_video: Any) -> Path:
    if not isinstance(raw_video, str) or not raw_video.strip():
        raise EvalConfigError(f"{case_path}: video must be a path")
    return (case_path.parent / raw_video).resolve()


def _target_config(
    workflow_metadata: Mapping[str, Any], raw_config: Mapping[str, Any]
) -> dict[str, Any]:
    config = {
        key: value
        for key, value in workflow_metadata.items()
        if key not in {"id", "label"}
    }
    config.update(raw_config)
    return config


def _preflight_case_expansion(raw_case: RawCaseFile, *, case_path: Path) -> None:
    total_samples = 0
    for target_id, raw_target in raw_case.targets.items():
        for block_index, raw_block in enumerate(raw_target.samples, start=1):
            total_samples += _sample_block_sample_count(
                raw_block, default_every_s=raw_case.sampling.every_s
            )
            if total_samples > MAX_EXPANDED_SAMPLES_PER_CASE:
                _raise_expansion_budget_error(
                    case_path=case_path,
                    target_id=target_id,
                    block_index=block_index,
                    calculated_count=total_samples,
                )


def _expand_sample_block(
    raw_block: RawSampleBlock,
    *,
    case_name: str,
    target_id: str,
    target_index: int,
    target_label: str | None,
    target_config: Mapping[str, Any],
    video_path: Path,
    default_every_s: float,
    next_sample_index: int,
    block_index: int,
    case_path: Path,
    intervals: list[tuple[float, float, str]],
) -> list[SampleExpectation]:
    compare = _compare_from_raw(raw_block.compare)
    timestamps = expand_sample_timestamps(
        raw_block,
        default_every_s=default_every_s,
        case_path=case_path,
        target_id=target_id,
        block_index=block_index,
    )

    if raw_block.range_ is not None:
        start, end = raw_block.range_
        source_interval = (start, end, f"sample {block_index}")
        _add_interval(intervals, source_interval, case_path, target_id, block_index)
        source = f"range [{source_interval[0]:g}, {source_interval[1]:g})"
    else:
        for timestamp in timestamps:
            _add_sample(intervals, timestamp, case_path, target_id, block_index)
        source = "at"

    return [
        SampleExpectation(
            case_name=case_name,
            target_id=target_id,
            target_index=target_index,
            target_label=target_label,
            target_config=target_config,
            video_path=video_path,
            timestamp_s=timestamp,
            sample_index=next_sample_index + offset,
            expected=raw_block.expect,
            field=raw_block.field,
            compare=compare,
            source=source,
            comment=raw_block.comment,
            ignore=raw_block.ignore,
        )
        for offset, timestamp in enumerate(timestamps)
    ]


def _compare_from_raw(raw_compare: RawCompare | None) -> ComparisonConfig:
    if raw_compare is None:
        return ComparisonConfig()
    return ComparisonConfig(
        mode=raw_compare.mode,
        tolerance=raw_compare.tolerance,
        raw=raw_compare.model_dump(exclude_none=True),
    )


def expand_sample_timestamps(
    raw_block: RawSampleBlock,
    *,
    default_every_s: float,
    case_path: Path,
    target_id: str,
    block_index: int,
) -> list[float]:
    """Expand one parsed block with the shared bounded timestamp rules."""
    sample_count = _sample_block_sample_count(
        raw_block, default_every_s=default_every_s
    )
    if sample_count > MAX_EXPANDED_SAMPLES_PER_CASE:
        _raise_expansion_budget_error(
            case_path=case_path,
            target_id=target_id,
            block_index=block_index,
            calculated_count=sample_count,
        )

    if raw_block.range_ is not None:
        start, _end = raw_block.range_
        every_s = (
            raw_block.every_s if raw_block.every_s is not None else default_every_s
        )
        timestamps: list[float] = []
        current = start
        for _ in range(sample_count):
            timestamps.append(_round_timestamp(current))
            current += every_s
    else:
        if raw_block.at is None:
            raise EvalConfigError(
                f"{case_path}: target {target_id!r} sample {block_index} "
                "at must contain at least one timestamp"
            )
        raw_values = raw_block.at if isinstance(raw_block.at, list) else [raw_block.at]
        timestamps = sorted(_round_timestamp(float(value)) for value in raw_values)
    _validate_normalized_timestamps(
        timestamps,
        case_path=case_path,
        target_id=target_id,
        block_index=block_index,
    )
    return timestamps


def _sample_block_sample_count(
    raw_block: RawSampleBlock, *, default_every_s: float
) -> int:
    if raw_block.range_ is None:
        return len(raw_block.at) if isinstance(raw_block.at, list | tuple) else 1

    start, end = raw_block.range_
    every_s = raw_block.every_s if raw_block.every_s is not None else default_every_s
    current = start
    threshold = end - _EPSILON
    for count in range(MAX_EXPANDED_SAMPLES_PER_CASE + 1):
        if not current < threshold:
            return count
        current += every_s
    prospective_count = _prospective_range_sample_count(start, end, every_s)
    return max(prospective_count, MAX_EXPANDED_SAMPLES_PER_CASE + 1)


def _prospective_range_sample_count(start: float, end: float, every_s: float) -> int:
    span = (end - _EPSILON) - start
    if span <= 0:
        return 0

    span_numerator, span_denominator = span.as_integer_ratio()
    step_numerator, step_denominator = every_s.as_integer_ratio()
    numerator = span_numerator * step_denominator
    denominator = span_denominator * step_numerator
    return (numerator + denominator - 1) // denominator


def _raise_expansion_budget_error(
    *,
    case_path: Path,
    target_id: str,
    block_index: int,
    calculated_count: int,
) -> None:
    raise EvalConfigError(
        f"{case_path}: target {target_id!r} sample {block_index} would expand "
        f"the case to {calculated_count} samples; limit is "
        f"{MAX_EXPANDED_SAMPLES_PER_CASE}"
    )


def _validate_normalized_timestamps(
    timestamps: list[float],
    *,
    case_path: Path,
    target_id: str,
    block_index: int,
) -> None:
    for previous, timestamp in zip(timestamps, timestamps[1:], strict=False):
        if _timestamp_tick(timestamp) - _timestamp_tick(previous) <= 1:
            raise EvalConfigError(
                f"{case_path}: target {target_id!r} sample {block_index} "
                f"timestamp {timestamp:g} duplicates timestamp {previous:g} "
                "after nine-decimal normalization"
            )


def _validate_target_normalized_timestamps(
    samples: list[SampleExpectation],
    *,
    case_path: Path,
    target_id: str,
) -> None:
    ordered = sorted(
        (_timestamp_tick(sample.timestamp_s), sample.timestamp_s) for sample in samples
    )
    for (previous_tick, previous), (tick, timestamp) in zip(
        ordered, ordered[1:], strict=False
    ):
        if tick - previous_tick <= 1:
            raise EvalConfigError(
                f"{case_path}: target {target_id!r} timestamps "
                f"{previous:.9f} and {timestamp:.9f} are within 1e-9 seconds "
                "after nine-decimal normalization"
            )


def _add_interval(
    intervals: list[tuple[float, float, str]],
    interval: tuple[float, float, str],
    case_path: Path,
    target_id: str,
    block_index: int,
) -> None:
    start, end, _source = interval
    for existing_start, existing_end, existing_source in intervals:
        if existing_start == existing_end:
            if start <= existing_start < end:
                raise EvalConfigError(
                    f"{case_path}: target {target_id!r} sample {block_index} "
                    f"overlaps {existing_source}"
                )
            continue
        if start < existing_end and existing_start < end:
            raise EvalConfigError(
                f"{case_path}: target {target_id!r} sample {block_index} "
                f"overlaps {existing_source}"
            )
    intervals.append(interval)


def _add_sample(
    intervals: list[tuple[float, float, str]],
    timestamp: float,
    case_path: Path,
    target_id: str,
    block_index: int,
) -> None:
    for existing_start, existing_end, existing_source in intervals:
        if existing_start == existing_end:
            if abs(timestamp - existing_start) <= _EPSILON:
                raise EvalConfigError(
                    f"{case_path}: target {target_id!r} sample {block_index} "
                    f"duplicates {existing_source}"
                )
            continue
        if existing_start <= timestamp < existing_end:
            raise EvalConfigError(
                f"{case_path}: target {target_id!r} sample {block_index} "
                f"overlaps {existing_source}"
            )
    intervals.append((timestamp, timestamp, f"sample {block_index}"))


def _thresholds_from_raw(raw_thresholds: RawThresholds) -> Thresholds:
    per_target = {
        target_id: TargetThreshold(min_pass_rate=raw_target.min_pass_rate)
        for target_id, raw_target in raw_thresholds.per_target.items()
    }
    return Thresholds(
        min_pass_rate=raw_thresholds.min_pass_rate,
        max_failures=raw_thresholds.max_failures,
        per_target=per_target,
    )


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _round_timestamp(value: float) -> float:
    return round(value, 9)


def _timestamp_tick(value: float) -> int:
    return int(Decimal(str(value)) * _NANOSECONDS_PER_SECOND)
