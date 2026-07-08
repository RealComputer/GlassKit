from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .models import (
    ComparisonConfig,
    EvalCase,
    EvalConfigError,
    EvalSuite,
    SampleExpectation,
    TargetSpec,
    TargetThreshold,
    Thresholds,
)
from .schemas import (
    RawCompare,
    RawSampleBlock,
    RawThresholds,
    parse_case_yaml,
    parse_eval_config_yaml,
    workflow_target_metadata,
)

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
YAML_SUFFIXES = (".yaml", ".yml")
EVAL_CONFIG_NAMES = ("config.yaml", "config.yml")
CASES_DIR_NAME = "cases"
_EPSILON = 1e-9


def load_eval_suite(
    eval_dir: Path,
    *,
    case_filter: str | None = None,
    target_filter: str | None = None,
    allow_empty: bool = False,
) -> EvalSuite:
    eval_dir = eval_dir.expanduser().resolve()
    if not eval_dir.exists():
        raise EvalConfigError(f"eval directory does not exist: {eval_dir}")
    if not eval_dir.is_dir():
        raise EvalConfigError(f"eval directory must be a directory: {eval_dir}")

    thresholds = _load_eval_thresholds(eval_dir)
    case_paths = _discover_case_paths(eval_dir, case_filter)
    target_id = (
        _normalize_target_filter(target_filter) if target_filter is not None else None
    )
    if target_id is not None:
        case_paths = _filter_case_paths_by_target(case_paths, target_id)
        if not case_paths:
            raise EvalConfigError(
                f"no eval targets found matching target {target_filter!r}"
            )
    cases = [_load_case(case_path, allow_empty=allow_empty) for case_path in case_paths]
    if target_id is not None:
        cases = _filter_cases_by_target(cases, target_id)
    if not allow_empty and not any(case.samples for case in cases):
        raise EvalConfigError("eval has no declared samples")
    return EvalSuite(path=eval_dir, cases=cases, thresholds=thresholds)


def format_sample_schedule(suite: EvalSuite) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in suite.cases:
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
                        "source": sample.source,
                    }
                )
    return rows


def _load_eval_thresholds(eval_dir: Path) -> Thresholds:
    paths = [
        child
        for child in eval_dir.iterdir()
        if child.is_file() and child.name in EVAL_CONFIG_NAMES
    ]
    if not paths:
        return Thresholds()
    if len(paths) > 1:
        names = ", ".join(path.name for path in paths)
        raise EvalConfigError(f"multiple eval config files found: {names}; keep one")
    path = paths[0]
    raw = parse_eval_config_yaml(_load_yaml_mapping(path), label=str(path))
    return _thresholds_from_raw(raw.thresholds)


def _discover_case_paths(eval_dir: Path, case_filter: str | None) -> list[Path]:
    cases_dir = eval_dir / CASES_DIR_NAME
    if not cases_dir.exists():
        raise EvalConfigError(f"eval cases directory does not exist: {cases_dir}")
    if not cases_dir.is_dir():
        raise EvalConfigError(f"eval cases path must be a directory: {cases_dir}")

    discovered = sorted(
        child
        for child in cases_dir.iterdir()
        if child.is_file() and child.suffix in YAML_SUFFIXES
    )
    if case_filter is not None:
        case_name = _normalize_case_filter(case_filter)
        candidates = [path for path in discovered if path.stem == case_name]
    else:
        candidates = discovered
    if not candidates:
        suffix = f" matching case {case_filter!r}" if case_filter else ""
        raise EvalConfigError(f"no eval cases found under {cases_dir}{suffix}")
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
        raise EvalConfigError(f"multiple eval case files share a name: {details}")


def _normalize_case_filter(case_filter: str) -> str:
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


def _normalize_target_filter(target_filter: str) -> str:
    if not target_filter or target_filter != target_filter.strip():
        raise EvalConfigError("target must be a target id from case YAML")
    return target_filter


def _filter_case_paths_by_target(case_paths: list[Path], target_id: str) -> list[Path]:
    return [
        case_path
        for case_path in case_paths
        if _case_yaml_declares_target(case_path, target_id)
    ]


def _case_yaml_declares_target(case_path: Path, target_id: str) -> bool:
    raw_targets = _load_yaml_mapping(case_path).get("targets")
    return isinstance(raw_targets, Mapping) and target_id in raw_targets


def _filter_cases_by_target(cases: list[EvalCase], target_id: str) -> list[EvalCase]:
    filtered: list[EvalCase] = []
    for case in cases:
        targets = [target for target in case.targets if target.id == target_id]
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


def _load_case(case_path: Path, *, allow_empty: bool) -> EvalCase:
    raw = parse_case_yaml(_load_yaml_mapping(case_path), label=str(case_path))

    video_path = _resolve_video_path(case_path, raw.video)
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


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
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


def _resolve_video_path(case_path: Path, raw_video: Any) -> Path:
    if not isinstance(raw_video, str) or not raw_video.strip():
        raise EvalConfigError(f"{case_path}: video must be a path")
    path = (case_path.parent / raw_video).resolve()
    if not path.exists():
        raise EvalConfigError(f"video file does not exist: {path}")
    if not path.is_file():
        raise EvalConfigError(f"video path is not a file: {path}")
    if path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        raise EvalConfigError(f"unsupported video file type: {path}")
    return path


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
    every_s = raw_block.every_s if raw_block.every_s is not None else default_every_s
    compare = _compare_from_raw(raw_block.compare)

    if raw_block.range_ is not None:
        timestamps, source_interval = _expand_range(
            raw_block.range_, every_s, case_path, target_id, block_index
        )
        _add_interval(intervals, source_interval, case_path, target_id, block_index)
        source = f"range [{source_interval[0]:g}, {source_interval[1]:g})"
    else:
        timestamps = _expand_at(raw_block.at, case_path, target_id, block_index)
        for timestamp in timestamps:
            _add_point(intervals, timestamp, case_path, target_id, block_index)
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


def _expand_range(
    raw_range: list[float],
    every_s: float,
    case_path: Path,
    target_id: str,
    block_index: int,
) -> tuple[list[float], tuple[float, float, str]]:
    start, end = raw_range
    timestamps: list[float] = []
    current = start
    while current < end - _EPSILON:
        timestamps.append(_round_timestamp(current))
        current += every_s
    return timestamps, (start, end, f"sample {block_index}")


def _expand_at(
    raw_at: Any,
    case_path: Path,
    target_id: str,
    block_index: int,
) -> list[float]:
    raw_values = raw_at if isinstance(raw_at, list | tuple) else [raw_at]
    timestamps = [_round_timestamp(float(value)) for value in raw_values]
    if not timestamps:
        raise EvalConfigError(
            f"{case_path}: target {target_id!r} sample {block_index} "
            "at must contain at least one timestamp"
        )
    return sorted(timestamps)


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


def _add_point(
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
