from __future__ import annotations

import base64
import io
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import av
from av import VideoFrame
from av.error import FFmpegError
from google import genai
from PIL import Image

from src.fold_check import compose_fold_check_image, parse_fold_check_result
from src.fold_check_prompts import (
    FOLD_CHECK_SYSTEM_PROMPT,
    fold_check_criteria_text,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_SERVICE_TIER = "flex"
GEMINI_IMAGE_RESOLUTION = "high"
GEMINI_LABEL_THINKING_LEVEL = "medium"
JPEG_QUALITY = 90
TIME_EPSILON = 1e-9


@dataclass(frozen=True)
class GeminiResult:
    value: bool
    response_text: str
    interaction_id: str | None


def label_camera_image(
    client: genai.Client,
    *,
    camera_image: Image.Image,
    reference_image: Image.Image,
    prompt: str,
    log_context: str,
) -> GeminiResult:
    composite = compose_fold_check_image(camera_image, reference_image)
    return call_fold_check_gemini(
        client,
        image=composite,
        prompt=prompt,
        log_context=log_context,
    )


def call_fold_check_gemini(
    client: genai.Client,
    *,
    image: Image.Image,
    prompt: str,
    log_context: str,
) -> GeminiResult:
    encoded_image = jpeg_base64(image)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            interaction = client.interactions.create(
                model=GEMINI_MODEL,
                system_instruction=FOLD_CHECK_SYSTEM_PROMPT,
                input=[
                    {"type": "text", "text": fold_check_criteria_text(prompt)},
                    {
                        "type": "image",
                        "data": encoded_image,
                        "mime_type": "image/jpeg",
                        "resolution": GEMINI_IMAGE_RESOLUTION,
                    },
                ],
                generation_config={"thinking_level": GEMINI_LABEL_THINKING_LEVEL},
                service_tier=GEMINI_SERVICE_TIER,
                store=False,
            )
            response_text = str(getattr(interaction, "output_text", "") or "").strip()
            parsed = parse_fold_check_result({"ok": True, "result": response_text})
            if parsed is None:
                raise RuntimeError(
                    f"Gemini returned non-boolean text: {response_text!r}"
                )
            return GeminiResult(
                value=parsed,
                response_text=response_text,
                interaction_id=cast("str | None", getattr(interaction, "id", None)),
            )
        except Exception as error:
            last_error = error
            if attempt == 3:
                break
            delay_s = 5 * (2 ** (attempt - 1))
            print(
                f"Gemini call failed for {log_context}; retrying in {delay_s}s: "
                f"{error}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay_s)
    raise RuntimeError(f"Gemini call failed for {log_context}: {last_error}")


def decode_sample_images(
    video_path: Path,
    timestamps_s: list[float],
) -> Iterator[tuple[str, Image.Image]]:
    if not timestamps_s:
        return

    requested = sorted({_time_value(timestamp_s) for timestamp_s in timestamps_s})
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
                current = (frame, timestamp_s, frame_index)
                while (
                    pending_index < len(requested)
                    and requested[pending_index] <= timestamp_s
                ):
                    requested_time_s = requested[pending_index]
                    chosen = _nearest_frame(previous, current, requested_time_s)
                    yield (
                        time_key(requested_time_s),
                        chosen[0].to_image().convert("RGB"),
                    )
                    pending_index += 1
                previous = current

            if previous is None:
                raise RuntimeError(f"video contains no frames: {video_path}")
            while pending_index < len(requested):
                requested_time_s = requested[pending_index]
                yield (
                    time_key(requested_time_s),
                    previous[0].to_image().convert("RGB"),
                )
                pending_index += 1
    except FFmpegError as error:
        raise RuntimeError(f"could not decode video {video_path}: {error}") from error


def jpeg_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer,
        format="JPEG",
        quality=max(1, min(100, JPEG_QUALITY)),
        optimize=True,
    )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def time_key(value: float) -> str:
    return f"{_time_value(value):.6f}"


def _video_stream(container: av.container.InputContainer) -> Any:
    stream = next(
        (candidate for candidate in container.streams if candidate.type == "video"),
        None,
    )
    if stream is None:
        raise RuntimeError("video file has no video stream")
    return stream


def _average_rate(stream: Any) -> float:
    if stream.average_rate:
        return float(stream.average_rate)
    return 30.0


def _frame_timestamp_s(frame: VideoFrame, frame_index: int, frame_rate: float) -> float:
    frame_time = cast("float | None", frame.time)
    if frame_time is not None:
        return frame_time
    pts = frame.pts
    time_base = frame.time_base
    if pts is not None and time_base is not None:
        return float(pts * time_base)
    return frame_index / frame_rate


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


def _time_value(value: float) -> float:
    rounded = round(value, 6)
    return 0.0 if abs(rounded) < TIME_EPSILON else rounded
