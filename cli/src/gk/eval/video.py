from __future__ import annotations

from pathlib import Path
from typing import Any

import av
from av import VideoFrame
from av.error import FFmpegError

from .models import EvalConfigError, FrameSample, SampleExpectation, VideoMetadata


def probe_video(video_path: Path) -> VideoMetadata:
    try:
        with av.open(str(video_path)) as container:
            stream = _video_stream(container)
            duration_s = _stream_duration_s(container, stream)
            width = int(stream.width or 0)
            height = int(stream.height or 0)
            frame_count = int(stream.frames) if stream.frames else None
    except FFmpegError as error:
        raise EvalConfigError(f"could not open video {video_path}: {error}") from error
    if duration_s <= 0:
        raise EvalConfigError(f"video has no readable duration: {video_path}")
    if width <= 0 or height <= 0:
        raise EvalConfigError(f"video has no readable dimensions: {video_path}")
    return VideoMetadata(
        path=video_path,
        duration_s=duration_s,
        width=width,
        height=height,
        frame_count=frame_count,
    )


def validate_sample_times(
    samples: list[SampleExpectation], metadata: VideoMetadata
) -> list[str]:
    issues: list[str] = []
    tolerance = 0.05
    for sample in samples:
        if sample.timestamp_s > metadata.duration_s + tolerance:
            issues.append(
                f"{sample.case_name}/{sample.target_id} sample "
                f"{sample.sample_index} at {sample.timestamp_s:g}s exceeds "
                f"video duration {metadata.duration_s:g}s"
            )
    return issues


def decode_sample_frames(
    video_path: Path, samples: list[SampleExpectation], *, case_name: str
) -> dict[int, FrameSample]:
    if not samples:
        return {}
    ordered = sorted(
        samples, key=lambda sample: (sample.timestamp_s, sample.sample_index)
    )
    decoded: dict[int, FrameSample] = {}
    try:
        with av.open(str(video_path)) as container:
            stream = _video_stream(container)
            frame_rate = _average_rate(stream)
            pending_index = 0
            frame_index = -1
            first_timestamp_s: float | None = None
            previous: tuple[VideoFrame, float, int] | None = None
            for frame in container.decode(stream):
                frame_index += 1
                raw_timestamp_s = _frame_timestamp_s(frame, frame_index, frame_rate)
                if first_timestamp_s is None:
                    first_timestamp_s = raw_timestamp_s
                timestamp_s = max(0.0, raw_timestamp_s - first_timestamp_s)
                while (
                    pending_index < len(ordered)
                    and ordered[pending_index].timestamp_s <= timestamp_s
                ):
                    sample = ordered[pending_index]
                    chosen = _nearest_frame(
                        previous, (frame, timestamp_s, frame_index), sample.timestamp_s
                    )
                    decoded[sample.sample_index] = _frame_sample(
                        chosen,
                        sample,
                        case_name=case_name,
                        video_path=video_path,
                    )
                    pending_index += 1
                previous = (frame, timestamp_s, frame_index)

            if previous is None:
                raise EvalConfigError(f"video contains no frames: {video_path}")
            while pending_index < len(ordered):
                sample = ordered[pending_index]
                decoded[sample.sample_index] = _frame_sample(
                    previous,
                    sample,
                    case_name=case_name,
                    video_path=video_path,
                )
                pending_index += 1
    except FFmpegError as error:
        raise EvalConfigError(
            f"could not decode video {video_path}: {error}"
        ) from error
    return decoded


def _frame_sample(
    chosen: tuple[VideoFrame, float, int],
    sample: SampleExpectation,
    *,
    case_name: str,
    video_path: Path,
) -> FrameSample:
    frame, _frame_time, frame_index = chosen
    return FrameSample(
        image=frame.to_image().convert("RGB"),
        timestamp_s=sample.timestamp_s,
        frame_index=frame_index,
        sample_index=sample.sample_index,
        video_path=str(video_path),
        case_name=case_name,
    )


def _nearest_frame(
    previous: tuple[VideoFrame, float, int] | None,
    current: tuple[VideoFrame, float, int],
    timestamp_s: float,
) -> tuple[VideoFrame, float, int]:
    if previous is None:
        return current
    previous_distance = abs(previous[1] - timestamp_s)
    current_distance = abs(current[1] - timestamp_s)
    return previous if previous_distance <= current_distance else current


def _video_stream(container: av.container.InputContainer) -> Any:
    stream = next(
        (candidate for candidate in container.streams if candidate.type == "video"),
        None,
    )
    if stream is None:
        raise EvalConfigError("video file has no video stream")
    return stream


def _stream_duration_s(container: Any, stream: Any) -> float:
    if stream.duration is not None and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return float(container.duration / av.time_base)
    if stream.frames and stream.average_rate:
        return float(stream.frames / stream.average_rate)
    return 0.0


def _average_rate(stream: Any) -> float:
    if stream.average_rate:
        return float(stream.average_rate)
    return 30.0


def _frame_timestamp_s(frame: VideoFrame, frame_index: int, frame_rate: float) -> float:
    if frame.time is not None:
        return float(frame.time)
    if frame.pts is not None and frame.time_base is not None:
        return float(frame.pts * frame.time_base)
    return frame_index / frame_rate
