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
    parse_expected_yaml,
    parse_suite_yaml,
    workflow_target_metadata,
)

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
_EPSILON = 1e-9


def load_eval_suite(
    suite_path: Path, *, case_filter: str | None = None, allow_empty: bool = False
) -> EvalSuite:
    suite_path = suite_path.expanduser().resolve()
    if not suite_path.exists():
        raise EvalConfigError(f"eval suite does not exist: {suite_path}")
    if not suite_path.is_dir():
        raise EvalConfigError(f"eval suite must be a directory: {suite_path}")

    thresholds = _load_suite_thresholds(suite_path)
    case_dirs = _discover_case_dirs(suite_path, case_filter)
    cases = [_load_case(case_dir, allow_empty=allow_empty) for case_dir in case_dirs]
    if not allow_empty and not any(case.samples for case in cases):
        raise EvalConfigError("eval suite has no declared samples")
    return EvalSuite(path=suite_path, cases=cases, thresholds=thresholds)


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
                        "timestamp_s": sample.timestamp_s,
                        "expected": sample.expected,
                        "field": sample.field,
                        "mode": sample.compare.mode,
                        "source": sample.source,
                    }
                )
    return rows


def _load_suite_thresholds(suite_path: Path) -> Thresholds:
    for filename in ("suite.yaml", "eval.yaml"):
        path = suite_path / filename
        if not path.exists():
            continue
        raw = parse_suite_yaml(_load_yaml_mapping(path), label=str(path))
        return _thresholds_from_raw(raw.thresholds)
    return Thresholds()


def _discover_case_dirs(suite_path: Path, case_filter: str | None) -> list[Path]:
    if (suite_path / "expected.yaml").exists():
        candidates = [suite_path]
    else:
        candidates = sorted(
            child
            for child in suite_path.iterdir()
            if child.is_dir() and (child / "expected.yaml").exists()
        )
    if case_filter is not None:
        candidates = [path for path in candidates if path.name == case_filter]
    if not candidates:
        suffix = f" matching case {case_filter!r}" if case_filter else ""
        raise EvalConfigError(f"no eval cases found under {suite_path}{suffix}")
    return candidates


def _load_case(case_dir: Path, *, allow_empty: bool) -> EvalCase:
    expected_path = case_dir / "expected.yaml"
    raw = parse_expected_yaml(
        _load_yaml_mapping(expected_path), label=str(expected_path)
    )

    video_path = _resolve_video_path(case_dir, raw.video)
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
                case_name=case_dir.name,
                target_id=target_id,
                target_index=target_index,
                target_label=label,
                target_config=target_config,
                video_path=video_path,
                default_every_s=raw.sampling.every_s,
                next_sample_index=next_sample_index,
                block_index=block_index,
                expected_path=expected_path,
                intervals=intervals,
            )
            samples.extend(block_samples)
            next_sample_index += len(block_samples)

        if not allow_empty and not samples:
            raise EvalConfigError(
                f"{expected_path}: target {target_id!r} has no samples"
            )
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
        raise EvalConfigError(f"{expected_path}: case has no samples")

    return EvalCase(
        name=case_dir.name,
        path=case_dir,
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


def _resolve_video_path(case_dir: Path, raw_video: Any) -> Path:
    if raw_video is not None:
        if not isinstance(raw_video, str) or not raw_video.strip():
            raise EvalConfigError(f"{case_dir / 'expected.yaml'}: video must be a path")
        path = (case_dir / raw_video).resolve()
        if not path.exists():
            raise EvalConfigError(f"video file does not exist: {path}")
        if path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
            raise EvalConfigError(f"unsupported video file type: {path}")
        return path

    videos = sorted(
        child
        for child in case_dir.iterdir()
        if child.is_file() and child.suffix.lower() in SUPPORTED_VIDEO_SUFFIXES
    )
    if len(videos) == 1:
        return videos[0].resolve()
    if not videos:
        raise EvalConfigError(f"{case_dir}: expected one video file or video: ...")
    raise EvalConfigError(
        f"{case_dir}: multiple video files found; set video: in expected.yaml"
    )


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
    expected_path: Path,
    intervals: list[tuple[float, float, str]],
) -> list[SampleExpectation]:
    every_s = raw_block.every_s if raw_block.every_s is not None else default_every_s
    compare = _compare_from_raw(raw_block.compare)

    if raw_block.range_ is not None:
        timestamps, source_interval = _expand_range(
            raw_block.range_, every_s, expected_path, target_id, block_index
        )
        _add_interval(intervals, source_interval, expected_path, target_id, block_index)
        source = f"range [{source_interval[0]:g}, {source_interval[1]:g})"
    else:
        timestamps = _expand_at(raw_block.at, expected_path, target_id, block_index)
        for timestamp in timestamps:
            _add_point(intervals, timestamp, expected_path, target_id, block_index)
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
    expected_path: Path,
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
    expected_path: Path,
    target_id: str,
    block_index: int,
) -> list[float]:
    raw_values = raw_at if isinstance(raw_at, list | tuple) else [raw_at]
    timestamps = [_round_timestamp(float(value)) for value in raw_values]
    if not timestamps:
        raise EvalConfigError(
            f"{expected_path}: target {target_id!r} sample {block_index} "
            "at must contain at least one timestamp"
        )
    return sorted(timestamps)


def _add_interval(
    intervals: list[tuple[float, float, str]],
    interval: tuple[float, float, str],
    expected_path: Path,
    target_id: str,
    block_index: int,
) -> None:
    start, end, _source = interval
    for existing_start, existing_end, existing_source in intervals:
        if existing_start == existing_end:
            if start <= existing_start < end:
                raise EvalConfigError(
                    f"{expected_path}: target {target_id!r} sample {block_index} "
                    f"overlaps {existing_source}"
                )
            continue
        if start < existing_end and existing_start < end:
            raise EvalConfigError(
                f"{expected_path}: target {target_id!r} sample {block_index} "
                f"overlaps {existing_source}"
            )
    intervals.append(interval)


def _add_point(
    intervals: list[tuple[float, float, str]],
    timestamp: float,
    expected_path: Path,
    target_id: str,
    block_index: int,
) -> None:
    for existing_start, existing_end, existing_source in intervals:
        if existing_start == existing_end:
            if abs(timestamp - existing_start) <= _EPSILON:
                raise EvalConfigError(
                    f"{expected_path}: target {target_id!r} sample {block_index} "
                    f"duplicates {existing_source}"
                )
            continue
        if existing_start <= timestamp < existing_end:
            raise EvalConfigError(
                f"{expected_path}: target {target_id!r} sample {block_index} "
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
