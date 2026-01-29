from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import supervision as sv
from aiortc import MediaStreamTrack
from inference import get_model
from PIL import Image

logger = logging.getLogger("uvicorn.error")


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


RFDETR_MODEL_ID = os.getenv("RFDETR_MODEL_ID", "test2-abpsp/4")
RFDETR_CONFIDENCE = _env_float("RFDETR_CONFIDENCE", 0.5)
RFDETR_MIN_INTERVAL_S = _env_float("RFDETR_MIN_INTERVAL_S", 0.4)
RFDETR_JPEG_QUALITY = _env_int("RFDETR_JPEG_QUALITY", 85)
RFDETR_HISTORY_LIMIT = _env_int("RFDETR_HISTORY_LIMIT", 200)
RFDETR_FRAMES_DIR = Path(
    os.getenv("RFDETR_FRAME_DIR", str(Path(__file__).with_name("frames")))
)
LABEL_MAP = {
    "wood panel": "BASE PANEL",
    "two-board wood panel": "LARGER SIDE PANELS",
    "plain narrow wood panel": "SHORTER SIDE PIECE",
    "narrow wood board with cutout": "HANDLE SIDE PIECE",
}


@dataclass(frozen=True)
class LatestFrame:
    data_uri: str
    jpeg_bytes: bytes
    timestamp: float
    labels: list[str]
    path: Path | None


class LatestFrameStore:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._latest: LatestFrame | None = None

    async def update(self, frame: LatestFrame) -> None:
        async with self._condition:
            self._latest = frame
            self._condition.notify_all()

    async def get_latest(self) -> LatestFrame | None:
        async with self._condition:
            return self._latest

    async def wait_for(self, timeout: float | None = None) -> LatestFrame | None:
        async with self._condition:
            if self._latest is not None:
                return self._latest
            if timeout is None:
                await self._condition.wait()
                return self._latest
            try:
                await asyncio.wait_for(self._condition.wait(), timeout)
            except asyncio.TimeoutError:
                return self._latest
            return self._latest


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
        store: LatestFrameStore,
        model_id: str = RFDETR_MODEL_ID,
        confidence: float = RFDETR_CONFIDENCE,
        min_interval_s: float = RFDETR_MIN_INTERVAL_S,
        jpeg_quality: int = RFDETR_JPEG_QUALITY,
        frames_dir: Path = RFDETR_FRAMES_DIR,
        history_limit: int = RFDETR_HISTORY_LIMIT,
    ) -> None:
        self._store = store
        self._model_id = model_id
        self._confidence = confidence
        self._min_interval_s = min_interval_s
        self._jpeg_quality = jpeg_quality
        self._processing = False
        self._last_processed = 0.0
        self._model_lock = asyncio.Lock()
        self._model = None
        self._box_annotator = sv.BoxAnnotator()
        self._label_annotator = sv.LabelAnnotator()
        self._frame_saver = FrameSaver(frames_dir, history_limit)

    async def consume(self, track: MediaStreamTrack) -> None:
        logger.info("vision: track started")
        while True:
            try:
                frame = await track.recv()
            except Exception:
                logger.info("vision: track ended")
                break
            await self._maybe_process_frame(frame)

    async def _maybe_process_frame(self, frame: Any) -> None:
        now = time.monotonic()
        if self._processing or (now - self._last_processed) < self._min_interval_s:
            return

        self._processing = True
        self._last_processed = now
        try:
            image = frame.to_ndarray(format="bgr24")
            model = await self._ensure_model()
            latest = await asyncio.to_thread(
                self._infer_annotate_and_save,
                model,
                image,
            )
            await self._store.update(latest)
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
            self._model = await asyncio.to_thread(
                get_model,
                model_id=self._model_id,
                api_key=api_key,
            )
            return self._model

    def _infer_annotate_and_save(self, model: Any, image: np.ndarray) -> LatestFrame:
        predictions = model.infer(image, confidence=self._confidence)[0]
        detections = sv.Detections.from_inference(predictions)

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

        data_uri = _to_data_uri(jpeg_bytes)
        return LatestFrame(
            data_uri=data_uri,
            jpeg_bytes=jpeg_bytes,
            timestamp=time.time(),
            labels=labels,
            path=path,
        )

    @staticmethod
    def _format_label(prediction: Any) -> str:
        label = str(getattr(prediction, "class_name", "object"))
        label = LABEL_MAP.get(label, label)
        confidence = getattr(prediction, "confidence", None)
        if isinstance(confidence, (int, float)):
            return f"{label} {confidence:.2f}"
        return label


def _encode_jpeg(rgb: np.ndarray, quality: int) -> bytes:
    image = Image.fromarray(rgb)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _to_data_uri(jpeg_bytes: bytes) -> str:
    payload = base64.b64encode(jpeg_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


def summarize_labels(labels: Iterable[str]) -> str:
    items = list(labels)
    if not items:
        return "no detections"
    return ", ".join(items)
