from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

from .expectations import load_eval_directory
from .models import EvalConfigError
from .video import iter_frames_at, probe_video


def export_case_frames(
    eval_dir: Path,
    *,
    case_selector: str,
    timestamps_s: Sequence[float],
    output_dir: Path | None = None,
) -> list[Path]:
    requested_timestamps = _normalize_timestamps(timestamps_s)
    eval_directory = load_eval_directory(
        eval_dir,
        case_filter=case_selector,
        allow_empty=True,
        allow_draft=True,
    )
    case = eval_directory.cases[0]
    metadata = probe_video(case.video_path)
    for timestamp_s in requested_timestamps:
        if timestamp_s > metadata.duration_s:
            raise EvalConfigError(
                f"requested time {timestamp_s:g}s exceeds video duration "
                f"{metadata.duration_s:g}s for case {case.name!r}"
            )

    destination = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else eval_directory.path / "runs" / "frames" / case.name
    )
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise EvalConfigError(
            f"could not create frame export directory {destination}: {error}"
        ) from error

    exported: list[Path | None] = [None] * len(requested_timestamps)
    selected_frames = iter_frames_at(case.video_path, requested_timestamps)
    try:
        for selected in selected_frames:
            path = destination / _frame_filename(selected.requested_timestamp_s)
            try:
                selected.image.save(path, format="PNG")
            except OSError as error:
                raise EvalConfigError(
                    f"could not export frame to {path}: {error}"
                ) from error
            finally:
                selected.image.close()
            exported[selected.request_index] = path
    finally:
        selected_frames.close()

    if any(path is None for path in exported):
        raise RuntimeError("internal error: video decoder did not produce every frame")
    return [path for path in exported if path is not None]


def _normalize_timestamps(timestamps_s: Sequence[float]) -> list[float]:
    if not timestamps_s:
        raise EvalConfigError("at least one frame time must be provided with --at")

    normalized: list[float] = []
    seen: set[float] = set()
    for timestamp_s in timestamps_s:
        if not math.isfinite(timestamp_s) or timestamp_s < 0:
            raise EvalConfigError("--at must be a finite, nonnegative number")
        timestamp_s = 0.0 if timestamp_s == 0 else timestamp_s
        if timestamp_s in seen:
            continue
        seen.add(timestamp_s)
        normalized.append(timestamp_s)
    return normalized


def _frame_filename(timestamp_s: float) -> str:
    return f"at-{timestamp_s}s.png"
