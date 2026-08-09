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
    EVAL_CONFIG_FILE_NAMES,
    discover_case_paths,
    expand_sample_timestamps,
    load_case,
    load_yaml_mapping,
    normalize_case_filter,
    normalize_target_filter,
    resolve_video_path,
)
from ..models import EvalCase, EvalConfigError, TargetSpec
from ..schemas import RawCaseFile, parse_case_file, parse_eval_config_file
from ..video import probe_video, validate_sample_times
from .models import (
    CaseFileDocument,
    CaseFileSummary,
    ErrorDetail,
    EvalDirectoryDocument,
    LoadError,
    ReplaceSamplesRequest,
    ReviewAPIError,
    ReviewSample,
    ReviewSampleDefaults,
    SampleCompare,
    SampleOrigin,
    TargetDocument,
    ValidationIssue,
    VideoDocument,
)
from .serialization import (
    atomic_replace_text,
    build_candidate_case_file,
    canonical_timestamp,
    compact_json,
    expectation_type,
    reconstruct_target,
)


class ReviewRepository:
    """Disk-backed source of review documents and atomic case file edits."""

    def __init__(self, eval_dir: Path) -> None:
        self.eval_dir = eval_dir.expanduser().resolve()
        # Discovery validates the eval and cases directory while intentionally
        # leaving malformed individual cases for per-case summaries.
        discover_case_paths(self.eval_dir)
        self._read_eval_config_file_source(validate=True)
        self._locks_guard = threading.Lock()
        self._case_locks: dict[Path, threading.RLock] = {}

    def eval_directory_document(self, *, write_token: str) -> EvalDirectoryDocument:
        paths = discover_case_paths(self.eval_dir)
        return EvalDirectoryDocument(
            eval_dir=str(self.eval_dir),
            write_token=write_token,
            eval_config_source=self._read_eval_config_file_source(validate=True),
            cases=[self._case_file_summary(path) for path in paths],
        )

    def case_file_document(self, case_id: str) -> CaseFileDocument:
        path = self._path_for_id(case_id)
        with self._lock_for(path):
            return self._case_file_document_unlocked(path)

    def replace_samples(
        self, case_id: str, request: ReplaceSamplesRequest
    ) -> CaseFileDocument:
        path = self._path_for_id(case_id)
        with self._lock_for(path):
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ReviewAPIError(
                    409,
                    "case_file_structure_changed",
                    "The case file is no longer valid UTF-8; reload it after repair.",
                ) from error
            except OSError as error:
                raise ReviewAPIError(
                    500,
                    "case_file_read_failed",
                    f"Could not read case file {path.name!r}: {error}",
                ) from error
            try:
                raw_mapping, raw_case = _parse_case_file_source(source, path)
            except EvalConfigError as error:
                raise ReviewAPIError(
                    409,
                    "case_file_structure_changed",
                    "The case file is no longer structurally editable; reload it.",
                ) from error

            candidate = build_candidate_case_file(raw_mapping, raw_case, request)
            try:
                _candidate_mapping, candidate_raw = _parse_case_file_source(
                    candidate.case_file_source, path
                )
                loaded = load_case(
                    path,
                    allow_empty=False,
                    allow_draft=True,
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
                    "The edited case file is not a valid eval case.",
                    [
                        # Existing eval errors already carry the target/sample context.
                        # Keep the transport path at the batch root when no narrower
                        # safe mapping is available.
                        ErrorDetail(path="targets", message=str(error))
                    ],
                ) from error

            try:
                directory_sync_failed = atomic_replace_text(
                    path, candidate.case_file_source
                )
            except OSError as error:
                raise ReviewAPIError(
                    500,
                    "write_failed",
                    f"Could not persist case file {path.name!r}: {error}",
                ) from error

            warnings: list[ValidationIssue] = []
            if directory_sync_failed:
                warnings.append(
                    ValidationIssue(
                        code="directory_sync_failed",
                        message=(
                            "The case file was replaced, but syncing its directory "
                            "failed. "
                            "The accepted content is shown below."
                        ),
                        severity="warning",
                        repairable=False,
                    )
                )
            return self._case_file_document_unlocked(
                path,
                sample_ids_by_target_tick=candidate.sample_ids_by_target_tick,
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
            raw = parse_case_file(load_yaml_mapping(path), label=str(path))
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
                raw = parse_case_file(load_yaml_mapping(path), label=str(path))
                return resolve_video_path(path, raw.video)
            except EvalConfigError as error:
                raise ReviewAPIError(
                    404,
                    "video_unavailable",
                    f"Video for case {path.name!r} is unavailable.",
                ) from error

    def _case_file_summary(self, path: Path) -> CaseFileSummary:
        description: str | None = None
        try:
            source = path.read_text(encoding="utf-8")
            _mapping, raw = _parse_case_file_source(source, path)
            description = raw.description
            loaded = load_case(
                path,
                allow_empty=True,
                allow_draft=True,
                raw_case=raw,
                resolve_video=False,
            )
        except UnicodeDecodeError as error:
            return CaseFileSummary(
                id=path.name,
                name=path.stem,
                file_name=path.name,
                description=None,
                target_count=None,
                sample_count=None,
                status="blocked",
                error=_load_error("invalid_encoding", str(error)),
            )
        except (OSError, EvalConfigError) as error:
            return CaseFileSummary(
                id=path.name,
                name=path.stem,
                file_name=path.name,
                description=description,
                target_count=None,
                sample_count=None,
                status="blocked",
                error=_load_error("invalid_case", str(error)),
            )
        return CaseFileSummary(
            id=path.name,
            name=path.stem,
            file_name=path.name,
            description=raw.description,
            target_count=len(loaded.targets),
            sample_count=len(loaded.samples),
            status="ready",
            error=None,
        )

    def _case_file_document_unlocked(
        self,
        path: Path,
        *,
        sample_ids_by_target_tick: dict[str, dict[int, str]] | None = None,
        response_issues: list[ValidationIssue] | None = None,
    ) -> CaseFileDocument:
        try:
            source_bytes = path.read_bytes()
        except OSError as error:
            raise ReviewAPIError(
                500,
                "case_file_read_failed",
                f"Could not read case file {path.name!r}: {error}",
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
            raw_mapping, raw_case = _parse_case_file_source(source, path)
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
                allow_draft=True,
                raw_case=raw_case,
                resolve_video=False,
            )
            targets = _target_documents(
                path,
                raw_mapping,
                raw_case,
                loaded,
                sample_ids_by_target_tick=sample_ids_by_target_tick or {},
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
            return CaseFileDocument(
                id=path.name,
                name=path.stem,
                revision=revision,
                status="blocked",
                editing_enabled=False,
                load_error=_load_error("video_unavailable", str(error)),
                description=raw_case.description,
                case_file_source=source,
                video=partial_video,
                targets=targets,
                validation_issues=response_issues or [],
            )

        issues = list(response_issues or [])
        target_samples = {target.id: target.samples for target in targets}
        for target in targets:
            if not target.samples:
                issues.append(
                    ValidationIssue(
                        code="empty_target",
                        message=f"Target {target.id!r} needs at least one sample.",
                        path=f"targets.{target.id}.samples",
                        severity="error",
                        repairable=True,
                    )
                )
            draft_count = sum(
                not sample.has_expectation and sample.ignore is None
                for sample in target.samples
            )
            if draft_count:
                noun = "sample" if draft_count == 1 else "samples"
                issues.append(
                    ValidationIssue(
                        code="draft_expectations",
                        message=(
                            f"Target {target.id!r} has {draft_count} draft {noun} "
                            "with no expectation."
                        ),
                        path=f"targets.{target.id}.samples",
                        severity="warning",
                        repairable=False,
                    )
                )
        for target_id, samples in target_samples.items():
            for sample in samples:
                if sample.timestamp_s > metadata.duration_s + 0.05:
                    issues.append(
                        ValidationIssue(
                            code="timestamp_after_video",
                            message=(
                                f"Sample at {sample.timestamp_s:g} seconds exceeds "
                                "video "
                                f"duration {metadata.duration_s:g} seconds."
                            ),
                            path=f"targets.{target_id}.samples.{sample.id}.timestamp_s",
                            severity="error",
                            repairable=True,
                        )
                    )

        repairable = any(
            issue.severity == "error" and issue.repairable for issue in issues
        )
        return CaseFileDocument(
            id=path.name,
            name=path.stem,
            revision=revision,
            status="repairable" if repairable else "ready",
            editing_enabled=True,
            load_error=None,
            description=raw_case.description,
            case_file_source=source,
            video=VideoDocument(
                url=f"/api/case-files/{quote(path.name, safe='')}/video",
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

    def _read_eval_config_file_source(self, *, validate: bool) -> str | None:
        paths = [
            child
            for child in self.eval_dir.iterdir()
            if child.is_file() and child.name in EVAL_CONFIG_FILE_NAMES
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
            parse_eval_config_file(load_yaml_mapping(path), label=str(path))
        return source

    def _path_for_id(self, case_id: str) -> Path:
        paths = {path.name: path for path in discover_case_paths(self.eval_dir)}
        path = paths.get(case_id)
        if path is None:
            raise ReviewAPIError(
                404, "case_file_not_found", f"No case file has id {case_id!r}."
            )
        return path

    def _lock_for(self, path: Path) -> threading.RLock:
        with self._locks_guard:
            return self._case_locks.setdefault(path, threading.RLock())


def _target_documents(
    case_path: Path,
    raw_mapping: Mapping[str, Any],
    raw_case: RawCaseFile,
    loaded: EvalCase,
    *,
    sample_ids_by_target_tick: dict[str, dict[int, str]],
) -> list[TargetDocument]:
    raw_targets = raw_mapping["targets"]
    assert isinstance(raw_targets, Mapping)
    loaded_by_id = {target.id: target for target in loaded.targets}
    documents: list[TargetDocument] = []
    for target_id, raw_target in raw_case.targets.items():
        loaded_target = loaded_by_id[target_id]
        samples = _samples_for_target(
            case_path,
            target_id,
            raw_target.samples,
            loaded_target,
            default_every_s=raw_case.sampling.every_s,
            id_overrides=sample_ids_by_target_tick.get(target_id, {}),
        )
        reconstructed = reconstruct_target(
            target_id,
            samples,
            default_every_s=raw_case.sampling.every_s,
            sample_defaults=loaded_target.sample_defaults,
        )
        samples_by_id = {sample.id: sample for sample in samples}
        sorted_samples = [samples_by_id[sample.id] for sample in reconstructed.samples]
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
                sample_defaults=ReviewSampleDefaults(
                    field=loaded_target.sample_defaults.field,
                    compare=SampleCompare(
                        mode=loaded_target.sample_defaults.compare.mode,
                        tolerance=loaded_target.sample_defaults.compare.tolerance,
                    ),
                ),
                samples=sorted_samples,
                display_groups=reconstructed.groups,
            )
        )
    return documents


def _samples_for_target(
    case_path: Path,
    target_id: str,
    raw_blocks: list[Any],
    loaded_target: TargetSpec,
    *,
    default_every_s: float,
    id_overrides: dict[int, str],
) -> list[ReviewSample]:
    samples: list[ReviewSample] = []
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
        for sample_index, sample in enumerate(block_samples):
            _canonical, tick = canonical_timestamp(sample.timestamp_s)
            sample_id = id_overrides.get(
                tick, f"block-{block_index}-sample-{sample_index}"
            )
            samples.append(
                ReviewSample(
                    id=sample_id,
                    timestamp_s=sample.timestamp_s,
                    has_expectation=sample.has_expectation,
                    expect_type=expectation_type(sample.expected),
                    expect_json=compact_json(sample.expected),
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
    if sample_offset != len(loaded_target.samples):
        raise EvalConfigError(
            f"{case_path}: target {target_id!r} sample expansion changed unexpectedly"
        )
    return samples


def _parse_case_file_source(
    source: str, path: Path
) -> tuple[dict[str, Any], RawCaseFile]:
    try:
        value = yaml.safe_load(source)
    except (yaml.YAMLError, RecursionError) as error:
        raise EvalConfigError(f"{path}: invalid YAML: {error}") from error
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise EvalConfigError(f"{path}: expected a YAML object")
    return value, parse_case_file(value, label=str(path))


def _blocked_document(
    path: Path,
    source_bytes: bytes,
    source: str,
    *,
    load_error: LoadError,
    description: str | None = None,
    video: VideoDocument | None = None,
) -> CaseFileDocument:
    return CaseFileDocument(
        id=path.name,
        name=path.stem,
        revision=hashlib.sha256(source_bytes).hexdigest(),
        status="blocked",
        editing_enabled=False,
        load_error=load_error,
        description=description,
        case_file_source=source,
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
