from __future__ import annotations

import asyncio
import logging
import time
from fractions import Fraction
from typing import Any

from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCRtpReceiver,
    RTCRtpSender,
)
from aiortc.codecs import h264 as aiortc_h264
from av import VideoFrame
from PIL import Image

from .constants import (
    AIORTC_H264_DEFAULT_BITRATE,
    AIORTC_H264_MAX_BITRATE,
    AIORTC_H264_MIN_BITRATE,
    DEMO_FPS,
    VIDEO_CLOCK_RATE,
)

logger = logging.getLogger("uvicorn.error")

# aiortc does not expose sender bitrate parameters; tune the H.264 codec module
# before any backend-originated demo encoders are created.
setattr(aiortc_h264, "DEFAULT_BITRATE", AIORTC_H264_DEFAULT_BITRATE)
setattr(aiortc_h264, "MIN_BITRATE", AIORTC_H264_MIN_BITRATE)
setattr(aiortc_h264, "MAX_BITRATE", AIORTC_H264_MAX_BITRATE)


class TimedVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, fps: int) -> None:
        super().__init__()
        self._fps = fps
        self._pts = 0
        self._next_frame_at = time.monotonic()

    async def _wait_tick(self) -> None:
        now = time.monotonic()
        if self._next_frame_at > now:
            await asyncio.sleep(self._next_frame_at - now)
        self._next_frame_at = max(
            self._next_frame_at + 1.0 / self._fps, time.monotonic()
        )

    def _video_frame_from_image(self, image: Image.Image) -> VideoFrame:
        frame = VideoFrame.from_image(image.convert("RGB"))
        frame.pts = self._pts
        frame.time_base = Fraction(1, VIDEO_CLOCK_RATE)
        self._pts += int(VIDEO_CLOCK_RATE / self._fps)
        return frame


class DemoCompositeTrack(TimedVideoTrack):
    def __init__(self, manager: Any) -> None:
        super().__init__(fps=DEMO_FPS)
        self._manager = manager

    async def recv(self) -> VideoFrame:
        await self._wait_tick()
        image = await self._manager.demo_frame_image()
        return self._video_frame_from_image(image)


async def _wait_for_ice_gathering_complete(pc: RTCPeerConnection) -> None:
    if pc.iceGatheringState == "complete":
        return
    done = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def on_ice_gathering_state_change() -> None:
        if pc.iceGatheringState == "complete":
            done.set()

    if pc.iceGatheringState == "complete":
        return
    try:
        await asyncio.wait_for(done.wait(), timeout=15.0)
    except TimeoutError:
        logger.warning("ICE gathering timed out; continuing with partial candidates")


def _prefer_codec(transceiver: Any, mime_type: str, *, sender: bool) -> None:
    try:
        capabilities = (
            RTCRtpSender.getCapabilities("video")
            if sender
            else RTCRtpReceiver.getCapabilities("video")
        )
    except Exception:
        logger.exception("failed to read video capabilities")
        return
    if capabilities is None:
        return
    lowered = mime_type.lower()
    preferences = [
        codec for codec in capabilities.codecs if codec.mimeType.lower() == lowered
    ]
    if preferences:
        transceiver.setCodecPreferences(preferences)


def create_peer_connection() -> RTCPeerConnection:
    return RTCPeerConnection(
        RTCConfiguration(
            iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
        )
    )
