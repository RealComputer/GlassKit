from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import numpy as np
import supervision as sv
from aiortc import MediaStreamTrack
from PIL import Image

from logging_utils import get_logger

_INFERENCE_WARNINGS_DISABLED = {
    "QWEN_2_5_ENABLED": "False",
    "QWEN_3_ENABLED": "False",
    "CORE_MODEL_SAM_ENABLED": "False",
    "CORE_MODEL_SAM3_ENABLED": "False",
    "CORE_MODEL_GAZE_ENABLED": "False",
    "CORE_MODEL_YOLO_WORLD_ENABLED": "False",
}
for name, value in _INFERENCE_WARNINGS_DISABLED.items():
    os.environ.setdefault(name, value)

logger = get_logger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%s; using default %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%s; using default %s", name, raw, default)
        return default


RFDETR_MODEL_ID = os.getenv("RFDETR_MODEL_ID", "sushi-3usqw/2")
RFDETR_CONFIDENCE = _env_float("RFDETR_CONFIDENCE", 0.7)
RFDETR_JPEG_QUALITY = _env_int("RFDETR_JPEG_QUALITY", 85)
RFDETR_HISTORY_LIMIT = _env_int("RFDETR_HISTORY_LIMIT", 1000)
RFDETR_FRAMES_DIR = Path(
    os.getenv("RFDETR_FRAME_DIR", str(Path(__file__).with_name("frames")))
)


@dataclass(frozen=True)
class DetectionResult:
    detected_classes: set[str]
    labels: list[str]
    jpeg_bytes: bytes
    timestamp: float
    path: Path | None


class LatestFrameBuffer:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._latest: tuple[int, Any] | None = None
        self._counter = 0
        self._closed = False

    async def update(self, frame: Any) -> None:
        async with self._condition:
            if self._closed:
                return
            self._counter += 1
            self._latest = (self._counter, frame)
            self._condition.notify_all()

    async def wait_for(self, last_id: int | None) -> tuple[int, Any] | None:
        async with self._condition:
            while not self._closed:
                if self._latest is not None and (
                    last_id is None or self._latest[0] != last_id
                ):
                    return self._latest
                await self._condition.wait()
            return None

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


class FrameSaver:
    def __init__(self, frames_dir: Path, history_limit: int) -> None:
        self._frames_dir = frames_dir
        self._history_limit = history_limit
        self._counter = 0
        self._lock = threading.Lock()
        self._frames_dir.mkdir(parents=True, exist_ok=True)

    def save(self, jpeg_bytes: bytes) -> Path:
        with self._lock:
            self._counter += 1
            timestamp_ms = int(time.time() * 1000)
            path = self._frames_dir / f"frame_{timestamp_ms}_{self._counter:06d}.jpg"
            path.write_bytes(jpeg_bytes)

            latest_path = self._frames_dir / "latest.jpg"
            latest_path.write_bytes(jpeg_bytes)

            if self._history_limit > 0:
                self._cleanup()
            return path

    def _cleanup(self) -> None:
        candidates = sorted(
            self._frames_dir.glob("frame_*.jpg"),
            key=lambda p: p.stat().st_mtime,
        )
        excess = len(candidates) - self._history_limit
        if excess <= 0:
            return
        for path in candidates[:excess]:
            try:
                path.unlink()
            except FileNotFoundError:
                continue


class VisionProcessor:
    def __init__(
        self,
        on_result: Callable[[DetectionResult], Awaitable[None]] | None = None,
        model_id: str = RFDETR_MODEL_ID,
        confidence: float = RFDETR_CONFIDENCE,
        jpeg_quality: int = RFDETR_JPEG_QUALITY,
        frames_dir: Path = RFDETR_FRAMES_DIR,
        history_limit: int = RFDETR_HISTORY_LIMIT,
    ) -> None:
        self._on_result = on_result
        self._model_id = model_id
        self._confidence = confidence
        self._jpeg_quality = jpeg_quality
        self._model_lock = asyncio.Lock()
        self._model: Any | None = None
        self._box_annotator = sv.BoxAnnotator()
        self._label_annotator = sv.LabelAnnotator()
        self._frame_saver = FrameSaver(frames_dir, history_limit)
        self._processing = False

    async def consume(self, track: MediaStreamTrack) -> None:
        logger.info("vision: track started")
        frame_buffer = LatestFrameBuffer()
        process_task = asyncio.create_task(self._process_loop(frame_buffer))

        try:
            while True:
                frame = await track.recv()
                await frame_buffer.update(frame)
        except Exception:
            logger.info("vision: track ended")
        finally:
            await frame_buffer.close()
            await process_task

    async def _process_loop(self, frame_buffer: LatestFrameBuffer) -> None:
        last_id: int | None = None
        while True:
            item = await frame_buffer.wait_for(last_id)
            if item is None:
                return
            frame_id, frame = item
            if frame_id == last_id:
                continue
            last_id = frame_id
            await self._process_frame(frame)

    async def _process_frame(self, frame: Any) -> None:
        if self._processing:
            return
        self._processing = True
        try:
            image = frame.to_ndarray(format="bgr24")
            model = await self._ensure_model()
            result = await asyncio.to_thread(
                self._infer_annotate_and_save,
                model,
                image,
            )
            if self._on_result:
                await self._on_result(result)
        except Exception:
            logger.exception("vision: processing failed")
        finally:
            self._processing = False

    async def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._model_lock:
            if self._model is not None:
                return self._model
            api_key = os.getenv("ROBOFLOW_API_KEY")
            if not api_key:
                raise RuntimeError("Set ROBOFLOW_API_KEY in env")
            from inference import get_model

            self._model = await asyncio.to_thread(
                get_model,
                model_id=self._model_id,
                api_key=api_key,
            )
            return self._model

    async def warmup(self) -> None:
        try:
            await self._ensure_model()
            logger.info("vision: model warmup complete")
        except Exception:
            logger.exception("vision: model warmup failed")

    def _infer_annotate_and_save(
        self, model: Any, image: np.ndarray
    ) -> DetectionResult:
        predictions = model.infer(image, confidence=self._confidence)[0]
        detections = sv.Detections.from_inference(predictions)

        detected_classes = {
            str(getattr(prediction, "class_name", ""))
            for prediction in getattr(predictions, "predictions", [])
            if getattr(prediction, "class_name", None)
        }

        labels = [
            self._format_label(prediction)
            for prediction in getattr(predictions, "predictions", [])
        ]

        annotated = image.copy()
        annotated = self._box_annotator.annotate(annotated, detections)
        annotated = self._label_annotator.annotate(annotated, detections, labels)

        rgb = annotated[:, :, ::-1]
        jpeg_bytes = _encode_jpeg(rgb, quality=self._jpeg_quality)
        path = self._frame_saver.save(jpeg_bytes)

        return DetectionResult(
            detected_classes=detected_classes,
            labels=labels,
            jpeg_bytes=jpeg_bytes,
            timestamp=time.time(),
            path=path,
        )

    @staticmethod
    def _format_label(prediction: Any) -> str:
        label = str(getattr(prediction, "class_name", "object"))
        confidence = getattr(prediction, "confidence", None)
        if isinstance(confidence, (int, float)):
            return f"{label} {confidence:.2f}"
        return label


def _encode_jpeg(rgb: np.ndarray, quality: int) -> bytes:
    image = Image.fromarray(rgb)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
