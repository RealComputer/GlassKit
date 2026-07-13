from __future__ import annotations

import copy
import errno
import json
import math
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from ..expectations import expand_sample_timestamps
from ..models import SUPPORTED_COMPARE_MODES, EvalConfigError
from ..schemas import RawCaseFile, RawSampleBlock
from .models import (
    DisplayGroup,
    ErrorDetail,
    ExpectType,
    GroupKind,
    ReplaceSamplesRequest,
    ReviewAPIError,
    ReviewSample,
    SampleOrigin,
)

NANOSECONDS_PER_SECOND = 1_000_000_000


class FlowSequence(list[Any]):
    """Marker for timestamp sequences that should use YAML flow style."""


class CaseFileDumper(yaml.SafeDumper):
    """Safe dumper with narrowly scoped compact timestamp sequences."""


def _represent_flow_sequence(
    dumper: CaseFileDumper, value: FlowSequence
) -> yaml.SequenceNode:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", value, flow_style=True)


CaseFileDumper.add_representer(FlowSequence, _represent_flow_sequence)


@dataclass(frozen=True)
class ParsedSample:
    id: str
    tick: int
    timestamp_s: float
    expect_type: ExpectType
    expected: Any
    field: str | None
    mode: str | None
    tolerance: float | None
    comment: str | None
    ignore: str | None
    origin: SampleOrigin | None


@dataclass(frozen=True)
class ReconstructedTarget:
    blocks: list[dict[str, Any]]
    groups: list[DisplayGroup]
    samples: list[ParsedSample]


@dataclass(frozen=True)
class CandidateCaseFile:
    case_file_source: str
    sample_ids_by_target_tick: dict[str, dict[int, str]]


def strict_json_value(text: str, *, path: str) -> Any:
    """Parse exactly one finite JSON-like value without numeric coercion."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number {value!r}")

    def object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=object_from_pairs,
        )
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        raise ReviewAPIError(
            422,
            "invalid_samples",
            "Target samples are invalid.",
            [ErrorDetail(path=path, message=f"must contain valid JSON: {error}")],
        ) from error
    try:
        issue = _json_value_issue(value)
    except RecursionError as error:
        raise ReviewAPIError(
            422,
            "invalid_samples",
            "Target samples are invalid.",
            [ErrorDetail(path=path, message="JSON value is nested too deeply")],
        ) from error
    if issue is not None:
        raise ReviewAPIError(
            422,
            "invalid_samples",
            "Target samples are invalid.",
            [ErrorDetail(path=path, message=issue)],
        )
    return value


def compact_json(value: Any) -> str:
    if issue := _json_value_issue(value):
        raise ValueError(issue)
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    # Successful API responses are UTF-8; reject YAML escapes that construct an
    # unpaired surrogate before they can poison response serialization.
    rendered.encode("utf-8")
    return rendered


def expectation_type(value: Any) -> ExpectType:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"unsupported expectation type: {type(value).__name__}")


def structurally_equal(left: Any, right: Any) -> bool:
    """Compare JSON values while keeping bool/int/float distinct."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return False
        return all(structurally_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            structurally_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if isinstance(left, float) and left == 0.0 and right == 0.0:
        return math.copysign(1.0, left) == math.copysign(1.0, right)
    return bool(left == right)


def canonical_timestamp(value: float) -> tuple[float, int]:
    canonical = round(value, 9)
    tick = int(Decimal(str(canonical)) * NANOSECONDS_PER_SECOND)
    return tick / NANOSECONDS_PER_SECOND, tick


def parse_samples(
    target_id: str, samples: Sequence[ReviewSample]
) -> list[ParsedSample]:
    parsed: list[ParsedSample] = []
    seen_ids: set[str] = set()
    for index, sample in enumerate(samples):
        path = f"targets.{target_id}.samples.{index}"
        if sample.id in seen_ids:
            raise ReviewAPIError(
                422,
                "invalid_samples",
                "Target samples are invalid.",
                [
                    ErrorDetail(
                        path=f"{path}.id",
                        message=f"duplicates sample id {sample.id!r} in this target",
                    )
                ],
            )
        seen_ids.add(sample.id)
        expected = strict_json_value(sample.expect_json, path=f"{path}.expect_json")
        actual_type = expectation_type(expected)
        if actual_type != sample.expect_type:
            raise ReviewAPIError(
                422,
                "invalid_samples",
                "Target samples are invalid.",
                [
                    ErrorDetail(
                        path=f"{path}.expect_type",
                        message=(
                            f"declares {sample.expect_type!r}, but expect_json "
                            "contains "
                            f"a {actual_type} value"
                        ),
                    )
                ],
            )
        if sample.compare.mode not in SUPPORTED_COMPARE_MODES | {None}:
            supported = ", ".join(sorted(SUPPORTED_COMPARE_MODES))
            raise ReviewAPIError(
                422,
                "invalid_samples",
                "Target samples are invalid.",
                [
                    ErrorDetail(
                        path=f"{path}.compare.mode",
                        message=f"must be one of: {supported}",
                    )
                ],
            )
        timestamp_s, tick = canonical_timestamp(sample.timestamp_s)
        parsed.append(
            ParsedSample(
                id=sample.id,
                tick=tick,
                timestamp_s=timestamp_s,
                expect_type=actual_type,
                expected=expected,
                field=sample.field,
                mode=sample.compare.mode,
                tolerance=sample.compare.tolerance,
                comment=sample.comment,
                ignore=sample.ignore,
                origin=sample.origin,
            )
        )
    parsed.sort(key=lambda sample: (sample.tick, sample.id))
    for index, sample in enumerate(parsed[1:], start=1):
        previous = parsed[index - 1]
        if sample.tick - previous.tick <= 1:
            raise ReviewAPIError(
                422,
                "invalid_samples",
                "Target samples are invalid.",
                [
                    ErrorDetail(
                        path=f"targets.{target_id}.samples",
                        message=(
                            f"sample {sample.id!r} at {sample.timestamp_s:g} seconds "
                            "is "
                            f"within 1e-9 seconds of sample {previous.id!r} at "
                            f"{previous.timestamp_s:g} seconds"
                        ),
                    )
                ],
            )
    return parsed


def reconstruct_target(
    target_id: str,
    samples: Sequence[ReviewSample],
    *,
    default_every_s: float,
) -> ReconstructedTarget:
    parsed = parse_samples(target_id, samples)
    if not parsed:
        return ReconstructedTarget(blocks=[], groups=[], samples=[])

    blocks: list[dict[str, Any]] = []
    grouped_samples: list[list[ParsedSample]] = []
    group_specs: list[tuple[GroupKind, int | None, int | None]] = []

    run_start = 0
    while run_start < len(parsed):
        run_end = run_start + 1
        while run_end < len(parsed) and _same_payload(
            parsed[run_start], parsed[run_end]
        ):
            run_end += 1
        _reconstruct_payload_run(
            parsed,
            run_start,
            run_end,
            default_every_s=default_every_s,
            blocks=blocks,
            grouped_samples=grouped_samples,
            group_specs=group_specs,
        )
        run_start = run_end

    groups: list[DisplayGroup] = []
    for index, (block_samples, spec) in enumerate(
        zip(grouped_samples, group_specs, strict=True)
    ):
        kind, end_tick, cadence_tick = spec
        groups.append(
            DisplayGroup(
                id=f"group-{index}",
                kind=kind,
                sample_ids=[sample.id for sample in block_samples],
                start_s=(block_samples[0].timestamp_s if kind == "range" else None),
                end_s=(_seconds_from_tick(end_tick) if end_tick is not None else None),
                every_s=(
                    _seconds_from_tick(cadence_tick)
                    if cadence_tick is not None
                    else None
                ),
                timestamps_s=[sample.timestamp_s for sample in block_samples],
            )
        )

    return ReconstructedTarget(blocks=blocks, groups=groups, samples=parsed)


def build_candidate_case_file(
    raw_mapping: Mapping[str, Any],
    raw_case: RawCaseFile,
    request: ReplaceSamplesRequest,
) -> CandidateCaseFile:
    targets_value = raw_mapping.get("targets")
    if not isinstance(targets_value, Mapping):
        raise ReviewAPIError(
            409,
            "case_file_structure_changed",
            "The case file's target structure changed on disk; reload it and try "
            "again.",
        )
    unknown = [
        target_id for target_id in request.targets if target_id not in targets_value
    ]
    if unknown:
        raise ReviewAPIError(
            409,
            "unknown_target",
            "One or more submitted targets no longer exist in the case file.",
            [
                ErrorDetail(
                    path=f"targets.{target_id}", message="target does not exist"
                )
                for target_id in unknown
            ],
        )

    # PyYAML constructs ordinary mutable ordered dicts on supported Python versions.
    candidate = dict(raw_mapping)
    candidate_targets = dict(targets_value)
    candidate["targets"] = candidate_targets
    sample_ids_by_target_tick: dict[str, dict[int, str]] = {}
    for target_id, replacement in request.targets.items():
        raw_target = candidate_targets[target_id]
        if not isinstance(raw_target, Mapping):
            raise ReviewAPIError(
                409,
                "case_file_structure_changed",
                "The case file's target structure changed on disk; reload it and "
                "try again.",
                [
                    ErrorDetail(
                        path=f"targets.{target_id}", message="must be a YAML object"
                    )
                ],
            )
        reconstructed = reconstruct_target(
            target_id,
            replacement.samples,
            default_every_s=raw_case.sampling.every_s,
        )
        replacement_target = dict(raw_target)
        replacement_target["samples"] = reconstructed.blocks
        candidate_targets[target_id] = replacement_target
        sample_ids_by_target_tick[target_id] = {
            sample.tick: sample.id for sample in reconstructed.samples
        }

    return CandidateCaseFile(
        case_file_source=dump_case_file(candidate),
        sample_ids_by_target_tick=sample_ids_by_target_tick,
    )


def dump_case_file(value: Mapping[str, Any]) -> str:
    styled = copy.deepcopy(value)
    targets = styled.get("targets") if isinstance(styled, Mapping) else None
    if isinstance(targets, Mapping):
        for target in targets.values():
            if not isinstance(target, Mapping):
                continue
            samples = target.get("samples")
            if not isinstance(samples, list):
                continue
            for block in samples:
                if not isinstance(block, dict):
                    continue
                if isinstance(block.get("range"), list):
                    block["range"] = FlowSequence(block["range"])
                if isinstance(block.get("at"), list):
                    block["at"] = FlowSequence(block["at"])
    return yaml.dump(
        styled,
        Dumper=CaseFileDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def atomic_replace_text(path: Path, case_file_source: str) -> bool:
    """Replace ``path`` atomically; return whether directory fsync failed."""

    original_mode = stat.S_IMODE(path.stat().st_mode)
    encoded = case_file_source.encode("utf-8")
    temporary_path: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(name)
        try:
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                fchmod(descriptor, original_mode)
            else:
                os.chmod(temporary_path, original_mode)
            stream = os.fdopen(descriptor, "wb")
            descriptor = -1  # The stream now owns and closes the descriptor.
            with stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    return _sync_directory(path.parent)


def _sync_directory(directory: Path) -> bool:
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if directory_flag is None:
        return False
    try:
        descriptor = os.open(directory, directory_flag | os.O_RDONLY)
    except OSError as error:
        unsupported = {errno.EINVAL, errno.ENOTSUP}
        if hasattr(errno, "EOPNOTSUPP"):
            unsupported.add(errno.EOPNOTSUPP)
        return error.errno not in unsupported
    sync_failed = False
    try:
        os.fsync(descriptor)
    except OSError:
        sync_failed = True
    try:
        os.close(descriptor)
    except OSError:
        sync_failed = True
    return sync_failed


def _reconstruct_payload_run(
    all_samples: list[ParsedSample],
    start: int,
    end: int,
    *,
    default_every_s: float,
    blocks: list[dict[str, Any]],
    grouped_samples: list[list[ParsedSample]],
    group_specs: list[tuple[GroupKind, int | None, int | None]],
) -> None:
    pending_at: list[ParsedSample] = []
    index = start
    while index < end:
        if index + 1 >= end:
            pending_at.append(all_samples[index])
            index += 1
            continue

        cadence_tick = all_samples[index + 1].tick - all_samples[index].tick
        candidate_end = index + 2
        while (
            candidate_end < end
            and all_samples[candidate_end].tick - all_samples[candidate_end - 1].tick
            == cadence_tick
        ):
            candidate_end += 1
        candidate = all_samples[index:candidate_end]
        range_eligible = len(candidate) >= 3 or (
            len(candidate) == 2
            and _two_sample_range_eligible(candidate, cadence_tick, default_every_s)
        )
        if not range_eligible:
            pending_at.append(all_samples[index])
            index += 1
            continue

        natural_end_tick = candidate[-1].tick + cadence_tick
        next_tick = (
            all_samples[candidate_end].tick
            if candidate_end < len(all_samples)
            else None
        )
        end_tick = (
            min(natural_end_tick, next_tick)
            if next_tick is not None
            else natural_end_tick
        )
        if not _range_expands_with_every(
            candidate, end_tick, _seconds_from_tick(cadence_tick)
        ):
            pending_at.extend(candidate)
            index = candidate_end
            continue

        _flush_at(pending_at, blocks, grouped_samples, group_specs)
        pending_at = []
        block = _payload_block(candidate[0])
        block_with_location: dict[str, Any] = {
            "range": FlowSequence(
                [candidate[0].timestamp_s, _seconds_from_tick(end_tick)]
            )
        }
        if not _range_expands_with_every(candidate, end_tick, default_every_s):
            block_with_location["every_s"] = _seconds_from_tick(cadence_tick)
        block_with_location.update(block)
        blocks.append(block_with_location)
        grouped_samples.append(candidate)
        group_specs.append(("range", end_tick, cadence_tick))
        index = candidate_end

    _flush_at(pending_at, blocks, grouped_samples, group_specs)


def _flush_at(
    samples: list[ParsedSample],
    blocks: list[dict[str, Any]],
    grouped_samples: list[list[ParsedSample]],
    group_specs: list[tuple[GroupKind, int | None, int | None]],
) -> None:
    if not samples:
        return
    location: float | FlowSequence
    if len(samples) == 1:
        location = samples[0].timestamp_s
    else:
        location = FlowSequence([sample.timestamp_s for sample in samples])
    block: dict[str, Any] = {"at": location}
    block.update(_payload_block(samples[0]))
    blocks.append(block)
    grouped_samples.append(list(samples))
    group_specs.append(("at", None, None))


def _payload_block(sample: ParsedSample) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if sample.field is not None:
        result["field"] = sample.field
    result["expect"] = sample.expected
    if sample.mode is not None or sample.tolerance is not None:
        compare: dict[str, Any] = {}
        if sample.mode is not None:
            compare["mode"] = sample.mode
        if sample.tolerance is not None:
            compare["tolerance"] = sample.tolerance
        result["compare"] = compare
    if sample.comment is not None:
        result["comment"] = sample.comment
    if sample.ignore is not None:
        result["ignore"] = sample.ignore
    return result


def _same_payload(left: ParsedSample, right: ParsedSample) -> bool:
    return (
        structurally_equal(left.expected, right.expected)
        and left.field == right.field
        and left.mode == right.mode
        and _same_optional_number(left.tolerance, right.tolerance)
        and left.comment == right.comment
        and left.ignore == right.ignore
    )


def _same_optional_number(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return type(left) is type(right) and left == right


def _two_sample_range_eligible(
    samples: list[ParsedSample], cadence_tick: int, default_every_s: float
) -> bool:
    natural_end_tick = samples[-1].tick + cadence_tick
    if _range_expands_with_every(samples, natural_end_tick, default_every_s):
        return True
    first_origin = samples[0].origin
    second_origin = samples[1].origin
    if (
        first_origin is None
        or second_origin is None
        or first_origin.kind != "range"
        or second_origin.kind != "range"
        or first_origin.block_index != second_origin.block_index
        or first_origin.every_s is None
        or second_origin.every_s is None
    ):
        return False
    origin_tick = canonical_timestamp(first_origin.every_s)[1]
    return origin_tick == canonical_timestamp(second_origin.every_s)[1] and (
        _range_expands_with_every(samples, natural_end_tick, first_origin.every_s)
    )


def _range_expands_with_every(
    samples: list[ParsedSample], end_tick: int, every_s: float
) -> bool:
    if every_s <= 0 or not math.isfinite(every_s):
        return False
    try:
        raw_block = RawSampleBlock.model_validate(
            {
                "range": [
                    _seconds_from_tick(samples[0].tick),
                    _seconds_from_tick(end_tick),
                ],
                "every_s": every_s,
                "expect": None,
            }
        )
        expanded = expand_sample_timestamps(
            raw_block,
            default_every_s=every_s,
            case_path=Path("<review-reconstruction>"),
            target_id="<target>",
            block_index=1,
        )
    except (EvalConfigError, ValueError, OverflowError):
        return False
    return [canonical_timestamp(value)[1] for value in expanded] == [
        sample.tick for sample in samples
    ]


def _seconds_from_tick(tick: int) -> float:
    return tick / NANOSECONDS_PER_SECOND


def _json_value_issue(value: Any, *, path: str = "value") -> str | None:
    if value is None or isinstance(value, bool | int):
        return None
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return f"{path} must contain valid Unicode scalar values"
        return None
    if isinstance(value, float):
        return None if math.isfinite(value) else f"{path} must be finite"
    if isinstance(value, list):
        for index, item in enumerate(value):
            if issue := _json_value_issue(item, path=f"{path}[{index}]"):
                return issue
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return f"{path} keys must be strings"
            try:
                key.encode("utf-8")
            except UnicodeEncodeError:
                return f"{path} keys must contain valid Unicode scalar values"
            if issue := _json_value_issue(item, path=f"{path}.{key}"):
                return issue
        return None
    return f"{path} must be JSON-like, got {type(value).__name__}"
