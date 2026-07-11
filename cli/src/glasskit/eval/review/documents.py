from __future__ import annotations

import hashlib
import mimetypes
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from ..expectations import (
    EVAL_CONFIG_NAMES,
    discover_case_paths,
    expand_sample_timestamps,
    load_case,
    load_yaml_mapping,
    normalize_case_filter,
    normalize_target_filter,
    resolve_video_path,
)
from ..models import EvalCase, EvalConfigError, TargetSpec
from ..schemas import RawCaseYaml, parse_case_yaml, parse_eval_config_yaml
from ..video import probe_video, validate_sample_times
from .models import (
    CaseDocument,
    CaseSummary,
    ErrorDetail,
    LoadError,
    PointCompare,
    PointOrigin,
    ReplaceSamplesRequest,
    ReviewAPIError,
    ReviewPoint,
    SuiteDocument,
    TargetDocument,
    ValidationIssue,
    VideoDocument,
)
from .serialization import (
    atomic_replace_text,
    build_candidate_case,
    canonical_timestamp,
    compact_json,
    expectation_type,
    reconstruct_target,
)


class ReviewRepository:
    """Disk-backed source of review documents and atomic case edits."""

    def __init__(self, eval_dir: Path) -> None:
        self.eval_dir = eval_dir.expanduser().resolve()
        # Discovery validates the eval and cases directory while intentionally
        # leaving malformed individual cases for per-case summaries.
        discover_case_paths(self.eval_dir)
        self._read_config_source(validate=True)
        self._locks_guard = threading.Lock()
        self._case_locks: dict[Path, threading.RLock] = {}

    def suite_document(self, *, write_token: str) -> SuiteDocument:
        paths = discover_case_paths(self.eval_dir)
        return SuiteDocument(
            eval_dir=str(self.eval_dir),
            write_token=write_token,
            config_source_yaml=self._read_config_source(validate=True),
            cases=[self._case_summary(path) for path in paths],
        )

    def case_document(self, case_id: str) -> CaseDocument:
        path = self._path_for_id(case_id)
        with self._lock_for(path):
            return self._case_document_unlocked(path)

    def replace_samples(
        self, case_id: str, request: ReplaceSamplesRequest
    ) -> CaseDocument:
        path = self._path_for_id(case_id)
        with self._lock_for(path):
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ReviewAPIError(
                    409,
                    "case_structure_changed",
                    "The case is no longer valid UTF-8; reload it after repair.",
                ) from error
            except OSError as error:
                raise ReviewAPIError(
                    500,
                    "case_read_failed",
                    f"Could not read case {path.name!r}: {error}",
                ) from error
            try:
                raw_mapping, raw_case = _parse_case_source(source, path)
            except EvalConfigError as error:
                raise ReviewAPIError(
                    409,
                    "case_structure_changed",
                    "The case is no longer structurally editable; reload it.",
                ) from error

            candidate = build_candidate_case(raw_mapping, raw_case, request)
            try:
                _candidate_mapping, candidate_raw = _parse_case_source(
                    candidate.source_yaml, path
                )
                loaded = load_case(
                    path,
                    allow_empty=False,
                    raw_case=candidate_raw,
                    resolve_video=True,
                )
                metadata = probe_video(loaded.video_path)
                time_issues = validate_sample_times(loaded.samples, metadata)
                if time_issues:
                    raise EvalConfigError("; ".join(time_issues))
            except EvalConfigError as error:
                raise ReviewAPIError(
                    422,
                    "invalid_samples",
                    "The edited case is not valid for normal eval loading.",
                    [
                        # Existing eval errors already carry the target/sample context.
                        # Keep the transport path at the batch root when no narrower
                        # safe mapping is available.
                        ErrorDetail(path="targets", message=str(error))
                    ],
                ) from error

            try:
                directory_sync_failed = atomic_replace_text(path, candidate.source_yaml)
            except OSError as error:
                raise ReviewAPIError(
                    500,
                    "write_failed",
                    f"Could not persist case {path.name!r}: {error}",
                ) from error

            warnings: list[ValidationIssue] = []
            if directory_sync_failed:
                warnings.append(
                    ValidationIssue(
                        code="directory_sync_failed",
                        message=(
                            "The case was replaced, but syncing its directory failed. "
                            "The accepted content is shown below."
                        ),
                        severity="warning",
                        repairable=False,
                    )
                )
            return self._case_document_unlocked(
                path,
                point_ids_by_target_tick=candidate.point_ids_by_target_tick,
                response_issues=warnings,
            )

    def resolve_case_selector(self, selector: str) -> str:
        normalized = normalize_case_filter(selector)
        paths = discover_case_paths(self.eval_dir, selector)
        path = next(
            (candidate for candidate in paths if candidate.stem == normalized), None
        )
        if path is None:  # Defensive: discovery normally raises before this branch.
            raise EvalConfigError(f"no case file found matching {selector!r}")
        return path.name

    def validate_target_selector(self, case_id: str, selector: str) -> str:
        target_id = normalize_target_filter(selector)
        path = self._path_for_id(case_id)
        try:
            raw = parse_case_yaml(load_yaml_mapping(path), label=str(path))
        except EvalConfigError:
            raise
        if target_id not in raw.targets:
            raise EvalConfigError(
                f"case {path.name!r} has no target matching {selector!r}"
            )
        return target_id

    def video_path(self, case_id: str) -> Path:
        path = self._path_for_id(case_id)
        with self._lock_for(path):
            try:
                raw = parse_case_yaml(load_yaml_mapping(path), label=str(path))
                return resolve_video_path(path, raw.video)
            except EvalConfigError as error:
                raise ReviewAPIError(
                    404,
                    "video_unavailable",
                    f"Video for case {path.name!r} is unavailable.",
                ) from error

    def _case_summary(self, path: Path) -> CaseSummary:
        description: str | None = None
        try:
            source = path.read_text(encoding="utf-8")
            _mapping, raw = _parse_case_source(source, path)
            description = raw.description
            loaded = load_case(
                path, allow_empty=True, raw_case=raw, resolve_video=False
            )
        except UnicodeDecodeError as error:
            return CaseSummary(
                id=path.name,
                name=path.stem,
                file_name=path.name,
                description=None,
                target_count=None,
                point_count=None,
                status="blocked",
                error=_load_error("invalid_encoding", str(error)),
            )
        except (OSError, EvalConfigError) as error:
            return CaseSummary(
                id=path.name,
                name=path.stem,
                file_name=path.name,
                description=description,
                target_count=None,
                point_count=None,
                status="blocked",
                error=_load_error("invalid_case", str(error)),
            )
        return CaseSummary(
            id=path.name,
            name=path.stem,
            file_name=path.name,
            description=raw.description,
            target_count=len(loaded.targets),
            point_count=len(loaded.samples),
            status="ready",
            error=None,
        )

    def _case_document_unlocked(
        self,
        path: Path,
        *,
        point_ids_by_target_tick: dict[str, dict[int, str]] | None = None,
        response_issues: list[ValidationIssue] | None = None,
    ) -> CaseDocument:
        try:
            source_bytes = path.read_bytes()
        except OSError as error:
            raise ReviewAPIError(
                500,
                "case_read_failed",
                f"Could not read case {path.name!r}: {error}",
            ) from error
        try:
            source = source_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            source = source_bytes.decode("utf-8", errors="replace")
            return _blocked_document(
                path,
                source_bytes,
                source,
                load_error=_load_error("invalid_encoding", str(error)),
            )

        revision = hashlib.sha256(source_bytes).hexdigest()
        try:
            raw_mapping, raw_case = _parse_case_source(source, path)
        except EvalConfigError as error:
            return _blocked_document(
                path,
                source_bytes,
                source,
                load_error=_load_error("invalid_case", str(error)),
                video=_partial_video_from_unparsed_source(source),
            )

        partial_video = VideoDocument(display_path=raw_case.video)
        try:
            loaded = load_case(
                path,
                allow_empty=True,
                raw_case=raw_case,
                resolve_video=False,
            )
            targets = _target_documents(
                path,
                raw_mapping,
                raw_case,
                loaded,
                point_ids_by_target_tick=point_ids_by_target_tick or {},
            )
        except (EvalConfigError, ReviewAPIError, ValueError, TypeError) as error:
            message = error.message if isinstance(error, ReviewAPIError) else str(error)
            return _blocked_document(
                path,
                source_bytes,
                source,
                description=raw_case.description,
                load_error=_load_error("invalid_samples", message),
                video=partial_video,
            )

        try:
            video_path = resolve_video_path(path, raw_case.video)
            metadata = probe_video(video_path)
        except EvalConfigError as error:
            return CaseDocument(
                id=path.name,
                name=path.stem,
                revision=revision,
                status="blocked",
                editing_enabled=False,
                load_error=_load_error("video_unavailable", str(error)),
                description=raw_case.description,
                source_yaml=source,
                video=partial_video,
                targets=targets,
                validation_issues=response_issues or [],
            )

        issues = list(response_issues or [])
        target_points = {target.id: target.points for target in targets}
        for target in targets:
            if not target.points:
                issues.append(
                    ValidationIssue(
                        code="empty_target",
                        message=f"Target {target.id!r} needs at least one sample.",
                        path=f"targets.{target.id}.samples",
                        severity="error",
                        repairable=True,
                    )
                )
        for target_id, points in target_points.items():
            for point in points:
                if point.timestamp_s > metadata.duration_s + 0.05:
                    issues.append(
                        ValidationIssue(
                            code="timestamp_after_video",
                            message=(
                                f"Sample at {point.timestamp_s:g} seconds exceeds "
                                "video "
                                f"duration {metadata.duration_s:g} seconds."
                            ),
                            path=f"targets.{target_id}.samples.{point.id}.timestamp_s",
                            severity="error",
                            repairable=True,
                        )
                    )

        repairable = any(
            issue.severity == "error" and issue.repairable for issue in issues
        )
        return CaseDocument(
            id=path.name,
            name=path.stem,
            revision=revision,
            status="repairable" if repairable else "ready",
            editing_enabled=True,
            load_error=None,
            description=raw_case.description,
            source_yaml=source,
            video=VideoDocument(
                url=f"/api/cases/{quote(path.name, safe='')}/video",
                display_path=raw_case.video,
                content_type=mimetypes.guess_type(video_path.name)[0]
                or "application/octet-stream",
                duration_s=metadata.duration_s,
                width=metadata.width,
                height=metadata.height,
                frame_count=metadata.frame_count,
            ),
            targets=targets,
            validation_issues=issues,
        )

    def _read_config_source(self, *, validate: bool) -> str | None:
        paths = [
            child
            for child in self.eval_dir.iterdir()
            if child.is_file() and child.name in EVAL_CONFIG_NAMES
        ]
        if not paths:
            return None
        if len(paths) > 1:
            names = ", ".join(path.name for path in sorted(paths))
            raise EvalConfigError(
                f"multiple eval config files found: {names}; keep one"
            )
        path = paths[0]
        source = path.read_text(encoding="utf-8")
        if validate:
            parse_eval_config_yaml(load_yaml_mapping(path), label=str(path))
        return source

    def _path_for_id(self, case_id: str) -> Path:
        paths = {path.name: path for path in discover_case_paths(self.eval_dir)}
        path = paths.get(case_id)
        if path is None:
            raise ReviewAPIError(
                404, "case_not_found", f"No review case has id {case_id!r}."
            )
        return path

    def _lock_for(self, path: Path) -> threading.RLock:
        with self._locks_guard:
            return self._case_locks.setdefault(path, threading.RLock())


def _target_documents(
    case_path: Path,
    raw_mapping: Mapping[str, Any],
    raw_case: RawCaseYaml,
    loaded: EvalCase,
    *,
    point_ids_by_target_tick: dict[str, dict[int, str]],
) -> list[TargetDocument]:
    raw_targets = raw_mapping["targets"]
    assert isinstance(raw_targets, Mapping)
    loaded_by_id = {target.id: target for target in loaded.targets}
    documents: list[TargetDocument] = []
    for target_id, raw_target in raw_case.targets.items():
        loaded_target = loaded_by_id[target_id]
        points = _points_for_target(
            case_path,
            target_id,
            raw_target.samples,
            loaded_target,
            default_every_s=raw_case.sampling.every_s,
            id_overrides=point_ids_by_target_tick.get(target_id, {}),
        )
        reconstructed = reconstruct_target(
            target_id, points, default_every_s=raw_case.sampling.every_s
        )
        points_by_id = {point.id: point for point in points}
        sorted_points = [points_by_id[point.id] for point in reconstructed.points]
        raw_target_mapping = raw_targets[target_id]
        details = (
            {
                key: value
                for key, value in raw_target_mapping.items()
                if key != "samples"
            }
            if isinstance(raw_target_mapping, Mapping)
            else {}
        )
        details_yaml = yaml.safe_dump(
            details, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
        documents.append(
            TargetDocument(
                id=target_id,
                label=loaded_target.label,
                details_yaml=details_yaml,
                points=sorted_points,
                display_groups=reconstructed.groups,
            )
        )
    return documents


def _points_for_target(
    case_path: Path,
    target_id: str,
    raw_blocks: list[Any],
    loaded_target: TargetSpec,
    *,
    default_every_s: float,
    id_overrides: dict[int, str],
) -> list[ReviewPoint]:
    points: list[ReviewPoint] = []
    sample_offset = 0
    for block_index, raw_block in enumerate(raw_blocks, start=1):
        timestamps = expand_sample_timestamps(
            raw_block,
            default_every_s=default_every_s,
            case_path=case_path,
            target_id=target_id,
            block_index=block_index,
        )
        block_samples = loaded_target.samples[
            sample_offset : sample_offset + len(timestamps)
        ]
        if len(block_samples) != len(timestamps):
            raise EvalConfigError(
                f"{case_path}: target {target_id!r} sample expansion "
                "changed unexpectedly"
            )
        kind = "range" if raw_block.range_ is not None else "at"
        effective_every = (
            raw_block.every_s if raw_block.every_s is not None else default_every_s
        )
        for point_index, sample in enumerate(block_samples):
            _canonical, tick = canonical_timestamp(sample.timestamp_s)
            point_id = id_overrides.get(
                tick, f"block-{block_index}-point-{point_index}"
            )
            points.append(
                ReviewPoint(
                    id=point_id,
                    timestamp_s=sample.timestamp_s,
                    expect_type=expectation_type(sample.expected),
                    expect_json=compact_json(sample.expected),
                    field=sample.field,
                    compare=PointCompare(
                        mode=sample.compare.mode,
                        tolerance=sample.compare.tolerance,
                    ),
                    comment=sample.comment,
                    origin=PointOrigin(
                        block_index=block_index,
                        kind=kind,
                        every_s=effective_every if kind == "range" else None,
                    ),
                )
            )
        sample_offset += len(timestamps)
    if sample_offset != len(loaded_target.samples):
        raise EvalConfigError(
            f"{case_path}: target {target_id!r} sample expansion changed unexpectedly"
        )
    return points


def _parse_case_source(source: str, path: Path) -> tuple[dict[str, Any], RawCaseYaml]:
    try:
        value = yaml.safe_load(source)
    except (yaml.YAMLError, RecursionError) as error:
        raise EvalConfigError(f"{path}: invalid YAML: {error}") from error
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise EvalConfigError(f"{path}: expected a YAML object")
    return value, parse_case_yaml(value, label=str(path))


def _blocked_document(
    path: Path,
    source_bytes: bytes,
    source: str,
    *,
    load_error: LoadError,
    description: str | None = None,
    video: VideoDocument | None = None,
) -> CaseDocument:
    return CaseDocument(
        id=path.name,
        name=path.stem,
        revision=hashlib.sha256(source_bytes).hexdigest(),
        status="blocked",
        editing_enabled=False,
        load_error=load_error,
        description=description,
        source_yaml=source,
        video=video,
        targets=[],
        validation_issues=[],
    )


def _partial_video_from_unparsed_source(source: str) -> VideoDocument | None:
    try:
        value = yaml.safe_load(source)
    except (yaml.YAMLError, RecursionError):
        return None
    if isinstance(value, Mapping) and isinstance(value.get("video"), str):
        try:
            return VideoDocument(display_path=value["video"])
        except ValueError:
            return None
    return None


def _load_error(code: str, message: str) -> LoadError:
    return LoadError(code=code, message=message, details=[])
