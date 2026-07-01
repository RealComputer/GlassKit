from __future__ import annotations

import asyncio
import logging
import queue
import threading
from fractions import Fraction
from pathlib import Path
from typing import cast

import av
from av.container.output import OutputContainer
from av import VideoFrame
from av.video.stream import VideoStream
from PIL import Image

logger = logging.getLogger("uvicorn.error")


class OvershootInputRecorder:
    def __init__(
        self,
        path: Path,
        *,
        fps: int,
        codec_name: str = "libx265",
        max_queue_size: int = 120,
    ) -> None:
        self.path = path
        self._fps = fps
        self._codec_name = codec_name
        self._queue: queue.Queue[Image.Image | None] = queue.Queue(max_queue_size)
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self.frames_enqueued = 0
        self.frames_dropped = 0
        self.frames_written = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._run,
            name=f"overshoot-input-recorder-{self.path.stem}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "overshoot input recording started path=%s codec=%s fps=%s",
            self.path,
            self._codec_name,
            self._fps,
        )

    def record(self, image: Image.Image) -> None:
        if self._closed.is_set() or self._thread is None:
            return
        try:
            self._queue.put_nowait(image)
        except queue.Full:
            self.frames_dropped += 1
            if self.frames_dropped == 1 or self.frames_dropped % 30 == 0:
                logger.warning(
                    "overshoot input recording queue full path=%s dropped=%s",
                    self.path,
                    self.frames_dropped,
                )
            return
        self.frames_enqueued += 1

    async def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return

        self._closed.set()
        while thread.is_alive():
            try:
                self._queue.put_nowait(None)
                break
            except queue.Full:
                await asyncio.sleep(0.01)
        await asyncio.to_thread(thread.join)
        self._thread = None

        if self._error is not None:
            logger.warning(
                "overshoot input recording failed path=%s error=%s",
                self.path,
                self._error,
            )
            return
        logger.info(
            "overshoot input recording stopped path=%s frames=%s dropped=%s",
            self.path,
            self.frames_written,
            self.frames_dropped,
        )

    def _run(self) -> None:
        container: OutputContainer | None = None
        stream: VideoStream | None = None
        output_size: tuple[int, int] | None = None
        frame_index = 0

        try:
            while True:
                image = self._queue.get()
                if image is None:
                    break

                if container is None or stream is None or output_size is None:
                    container, stream, output_size = self._open_output(image)

                frame = self._video_frame(image, frame_index, output_size)
                for packet in stream.encode(frame):
                    container.mux(packet)
                frame_index += 1
                self.frames_written += 1

            if container is not None and stream is not None:
                for packet in stream.encode(None):
                    container.mux(packet)
        except BaseException as error:
            self._error = error
            logger.exception("overshoot input recording crashed path=%s", self.path)
        finally:
            if container is not None:
                container.close()

    def _open_output(
        self, image: Image.Image
    ) -> tuple[OutputContainer, VideoStream, tuple[int, int]]:
        width, height = _even_size(image.size)
        container = av.open(str(self.path), mode="w", format="mp4")
        stream = cast(
            VideoStream, container.add_stream(self._codec_name, rate=self._fps)
        )
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, self._fps)
        stream.codec_context.time_base = Fraction(1, self._fps)
        if self._codec_name == "libx265":
            stream.codec_context.options = {
                "preset": "ultrafast",
                "x265-params": "log-level=error",
            }
        return container, stream, (width, height)

    def _video_frame(
        self,
        image: Image.Image,
        frame_index: int,
        output_size: tuple[int, int],
    ) -> VideoFrame:
        if image.size != output_size:
            image = image.convert("RGB").resize(output_size, Image.Resampling.BILINEAR)
        else:
            image = image.convert("RGB")

        frame = VideoFrame.from_image(image)
        frame.pts = frame_index
        frame.time_base = Fraction(1, self._fps)
        return frame


def _even_size(size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    return max(2, width - (width % 2)), max(2, height - (height % 2))
