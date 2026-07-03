from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

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

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
DEFAULT_EVERY_S = 0.5
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
        raw = _load_yaml_mapping(path)
        return _parse_thresholds(raw.get("thresholds"), path=path)
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
    raw = _load_yaml_mapping(expected_path)

    version = raw.get("version", 1)
    if version != 1:
        raise EvalConfigError(f"{expected_path}: unsupported version {version!r}")

    video_path = _resolve_video_path(case_dir, raw.get("video"))
    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        raise EvalConfigError(f"{expected_path}: description must be a string")

    sampling = raw.get("sampling") or {}
    if not isinstance(sampling, Mapping):
        raise EvalConfigError(f"{expected_path}: sampling must be an object")
    default_every_s = _positive_float(
        sampling.get("every_s", DEFAULT_EVERY_S),
        f"{expected_path}: sampling.every_s",
    )

    workflow_targets = _workflow_target_metadata(raw.get("workflow"), expected_path)
    raw_targets = raw.get("targets")
    if not isinstance(raw_targets, Mapping):
        raise EvalConfigError(f"{expected_path}: targets must be an object")

    targets: list[TargetSpec] = []
    next_sample_index = 0
    for target_index, (target_id, raw_target) in enumerate(raw_targets.items()):
        if not isinstance(target_id, str) or not target_id.strip():
            raise EvalConfigError(f"{expected_path}: target ids must be strings")
        if not isinstance(raw_target, Mapping):
            raise EvalConfigError(
                f"{expected_path}: target {target_id!r} must be an object"
            )

        metadata = workflow_targets.get(target_id, {})
        label = _optional_string(raw_target.get("label")) or _optional_string(
            metadata.get("label")
        )
        target_config = _target_config(
            metadata,
            cast("Mapping[str, Any]", raw_target),
        )
        raw_samples = raw_target.get("samples")
        if not isinstance(raw_samples, list):
            raise EvalConfigError(
                f"{expected_path}: target {target_id!r} samples must be a list"
            )

        samples: list[SampleExpectation] = []
        intervals: list[tuple[float, float, str]] = []
        for block_index, raw_block in enumerate(raw_samples, start=1):
            block_samples = _expand_sample_block(
                raw_block,
                case_name=case_dir.name,
                target_id=target_id,
                target_index=target_index,
                target_label=label,
                target_config=target_config,
                video_path=video_path,
                default_every_s=default_every_s,
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
        description=description,
        targets=targets,
        thresholds=_parse_thresholds(raw.get("thresholds"), path=expected_path),
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


def _workflow_target_metadata(raw_workflow: Any, expected_path: Path) -> dict[str, Any]:
    if raw_workflow is None:
        return {}
    if not isinstance(raw_workflow, Mapping):
        raise EvalConfigError(f"{expected_path}: workflow must be an object")
    raw_targets = raw_workflow.get("targets", [])
    if raw_targets is None:
        return {}
    if not isinstance(raw_targets, list):
        raise EvalConfigError(f"{expected_path}: workflow.targets must be a list")
    metadata: dict[str, Any] = {}
    for index, raw_target in enumerate(raw_targets, start=1):
        if not isinstance(raw_target, Mapping):
            raise EvalConfigError(
                f"{expected_path}: workflow target {index} must be an object"
            )
        target_id = raw_target.get("id")
        if not isinstance(target_id, str) or not target_id.strip():
            raise EvalConfigError(
                f"{expected_path}: workflow target {index} id must be a string"
            )
        metadata[target_id.strip()] = dict(raw_target)
    return metadata


def _target_config(
    workflow_metadata: Mapping[str, Any], raw_target: Mapping[str, Any]
) -> dict[str, Any]:
    config = {
        key: value
        for key, value in workflow_metadata.items()
        if key not in {"id", "label"}
    }
    raw_config = raw_target.get("config")
    if raw_config is not None:
        if not isinstance(raw_config, Mapping):
            raise EvalConfigError("target config must be an object")
        config.update(raw_config)
    return config


def _expand_sample_block(
    raw_block: Any,
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
    if not isinstance(raw_block, Mapping):
        raise EvalConfigError(
            f"{expected_path}: target {target_id!r} sample {block_index} "
            "must be an object"
        )
    has_range = "range" in raw_block
    has_at = "at" in raw_block
    if has_range == has_at:
        raise EvalConfigError(
            f"{expected_path}: target {target_id!r} sample {block_index} "
            "must contain exactly one of range or at"
        )
    if "expect" not in raw_block:
        raise EvalConfigError(
            f"{expected_path}: target {target_id!r} sample {block_index} "
            "must contain expect"
        )

    every_s = _positive_float(
        raw_block.get("every_s", default_every_s),
        f"{expected_path}: target {target_id!r} sample {block_index} every_s",
    )
    expected = raw_block["expect"]
    field = raw_block.get("field")
    if field is not None and not isinstance(field, str):
        raise EvalConfigError(
            f"{expected_path}: target {target_id!r} sample {block_index} field "
            "must be a string"
        )
    compare = _parse_compare(raw_block.get("compare"), expected_path)

    if has_range:
        timestamps, source_interval = _expand_range(
            raw_block["range"], every_s, expected_path, target_id, block_index
        )
        _add_interval(intervals, source_interval, expected_path, target_id, block_index)
        source = f"range [{source_interval[0]:g}, {source_interval[1]:g})"
    else:
        timestamps = _expand_at(raw_block["at"], expected_path, target_id, block_index)
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
            expected=expected,
            field=field,
            compare=compare,
            source=source,
        )
        for offset, timestamp in enumerate(timestamps)
    ]


def _parse_compare(raw_compare: Any, expected_path: Path) -> ComparisonConfig:
    if raw_compare is None:
        return ComparisonConfig()
    if not isinstance(raw_compare, Mapping):
        raise EvalConfigError(f"{expected_path}: compare must be an object")
    mode = raw_compare.get("mode")
    if mode is not None and not isinstance(mode, str):
        raise EvalConfigError(f"{expected_path}: compare.mode must be a string")
    tolerance = raw_compare.get("tolerance")
    parsed_tolerance = None
    if tolerance is not None:
        parsed_tolerance = _non_negative_float(tolerance, f"{expected_path}: tolerance")
    return ComparisonConfig(
        mode=mode.strip() if isinstance(mode, str) else None,
        tolerance=parsed_tolerance,
        raw=dict(raw_compare),
    )


def _expand_range(
    raw_range: Any,
    every_s: float,
    expected_path: Path,
    target_id: str,
    block_index: int,
) -> tuple[list[float], tuple[float, float, str]]:
    if (
        not isinstance(raw_range, list | tuple)
        or len(raw_range) != 2
        or isinstance(raw_range, str)
    ):
        raise EvalConfigError(
            f"{expected_path}: target {target_id!r} sample {block_index} "
            "range must be [start, end]"
        )
    start = _non_negative_float(
        raw_range[0],
        f"{expected_path}: target {target_id!r} sample {block_index} range start",
    )
    end = _non_negative_float(
        raw_range[1],
        f"{expected_path}: target {target_id!r} sample {block_index} range end",
    )
    if end <= start:
        raise EvalConfigError(
            f"{expected_path}: target {target_id!r} sample {block_index} "
            "range end must be greater than start"
        )
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
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    timestamps = [
        _round_timestamp(
            _non_negative_float(
                value,
                f"{expected_path}: target {target_id!r} sample {block_index} at",
            )
        )
        for value in raw_values
    ]
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


def _parse_thresholds(raw_thresholds: Any, *, path: Path) -> Thresholds:
    if raw_thresholds is None:
        return Thresholds()
    if not isinstance(raw_thresholds, Mapping):
        raise EvalConfigError(f"{path}: thresholds must be an object")
    min_pass_rate = _optional_rate(raw_thresholds.get("min_pass_rate"), path)
    max_failures = raw_thresholds.get("max_failures")
    parsed_max_failures = None
    if max_failures is not None:
        if not isinstance(max_failures, int) or max_failures < 0:
            raise EvalConfigError(f"{path}: thresholds.max_failures must be >= 0")
        parsed_max_failures = max_failures

    per_target: dict[str, TargetThreshold] = {}
    raw_per_target = raw_thresholds.get("per_target") or {}
    if not isinstance(raw_per_target, Mapping):
        raise EvalConfigError(f"{path}: thresholds.per_target must be an object")
    for target_id, raw_target in raw_per_target.items():
        if not isinstance(target_id, str) or not target_id.strip():
            raise EvalConfigError(f"{path}: per-target threshold ids must be strings")
        if not isinstance(raw_target, Mapping):
            raise EvalConfigError(
                f"{path}: threshold for target {target_id!r} must be an object"
            )
        per_target[target_id] = TargetThreshold(
            min_pass_rate=_optional_rate(raw_target.get("min_pass_rate"), path)
        )
    return Thresholds(
        min_pass_rate=min_pass_rate,
        max_failures=parsed_max_failures,
        per_target=per_target,
    )


def _optional_rate(raw_value: Any, path: Path) -> float | None:
    if raw_value is None:
        return None
    value = _non_negative_float(raw_value, f"{path}: pass rate")
    if value > 1:
        raise EvalConfigError(f"{path}: pass rate must be between 0 and 1")
    return value


def _positive_float(value: Any, label: str) -> float:
    parsed = _non_negative_float(value, label)
    if parsed <= 0:
        raise EvalConfigError(f"{label} must be greater than 0")
    return parsed


def _non_negative_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise EvalConfigError(f"{label} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise EvalConfigError(f"{label} must be a number") from error
    if parsed < 0:
        raise EvalConfigError(f"{label} must be non-negative")
    return parsed


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _round_timestamp(value: float) -> float:
    return round(value, 9)
