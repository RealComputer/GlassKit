from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from math import atan2, degrees
from pathlib import Path
from struct import unpack
from typing import Any

import av
from av import VideoFrame
from av.error import FFmpegError
from PIL import Image, ImageOps

from .models import EvalConfigError, FrameSample, SampleExpectation, VideoMetadata


def probe_video(video_path: Path) -> VideoMetadata:
    try:
        with av.open(str(video_path)) as container:
            stream = _video_stream(container)
            duration_s = _stream_duration_s(container, stream)
            width = int(stream.width or 0)
            height = int(stream.height or 0)
            frame_count = int(stream.frames) if stream.frames else None
            first_frame = next(container.decode(stream), None)
            if first_frame is not None and width > 0 and height > 0:
                width, height = _display_dimensions(
                    width,
                    height,
                    _display_transform(first_frame),
                )
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
    return {
        sample.sample_index: sample
        for sample in iter_sample_frames(video_path, samples, case_name=case_name)
    }


def iter_sample_frames(
    video_path: Path, samples: list[SampleExpectation], *, case_name: str
) -> Generator[FrameSample, None, None]:
    if not samples:
        return
    ordered = sorted(
        samples, key=lambda sample: (sample.timestamp_s, sample.sample_index)
    )
    try:
        with av.open(str(video_path)) as container:
            stream = _video_stream(container)
            stream.thread_type = "AUTO"
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
                    yield _frame_sample(
                        chosen,
                        sample,
                        case_name=case_name,
                        video_path=video_path,
                    )
                    pending_index += 1
                previous = (frame, timestamp_s, frame_index)
                if pending_index == len(ordered):
                    break

            if previous is None:
                raise EvalConfigError(f"video contains no frames: {video_path}")
            while pending_index < len(ordered):
                sample = ordered[pending_index]
                yield _frame_sample(
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


def _frame_sample(
    chosen: tuple[VideoFrame, float, int],
    sample: SampleExpectation,
    *,
    case_name: str,
    video_path: Path,
) -> FrameSample:
    frame, _frame_time, frame_index = chosen
    return FrameSample(
        image=_display_image(frame),
        timestamp_s=sample.timestamp_s,
        frame_index=frame_index,
        sample_index=sample.sample_index,
        video_path=str(video_path),
        case_name=case_name,
    )


def _display_image(frame: VideoFrame) -> Image.Image:
    image = frame.to_image().convert("RGB")
    transform = _display_transform(frame)
    if transform.rotation == 0 and not transform.reflected:
        return image

    rotated = image.rotate(transform.rotation, expand=True)
    image.close()
    if not transform.reflected:
        return rotated

    displayed = ImageOps.mirror(rotated)
    rotated.close()
    return displayed


def _display_rotation(frame: VideoFrame) -> int:
    return int(frame.rotation or 0) % 360


@dataclass(frozen=True)
class _DisplayTransform:
    rotation: int
    reflected: bool = False


def _display_transform(frame: VideoFrame) -> _DisplayTransform:
    rotation = _display_rotation(frame)
    for side_data in getattr(frame, "side_data", ()):
        side_data_type = getattr(side_data, "type", None)
        if getattr(side_data_type, "name", None) != "DISPLAYMATRIX":
            continue
        matrix_bytes = bytes(side_data)
        if len(matrix_bytes) != 36:
            continue
        a, b, _, c, d, _, _, _, _ = unpack("=9i", matrix_bytes)
        if a * d - b * c >= 0:
            break

        reflected_rotation = round(degrees(atan2(-b, -a))) % 360
        return _DisplayTransform(rotation=reflected_rotation, reflected=True)
    return _DisplayTransform(rotation=rotation)


def _display_dimensions(
    width: int, height: int, transform: _DisplayTransform
) -> tuple[int, int]:
    rotation = transform.rotation
    if rotation in {0, 180}:
        return width, height
    if rotation in {90, 270}:
        return height, width

    image = Image.new("1", (width, height))
    try:
        displayed = image.rotate(rotation, expand=True)
        try:
            return displayed.size
        finally:
            displayed.close()
    finally:
        image.close()


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
