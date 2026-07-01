from __future__ import annotations

import asyncio
import logging
import time
from fractions import Fraction
from typing import TYPE_CHECKING, Any

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
    OVERSHOOT_FPS,
    VIDEO_CLOCK_RATE,
)
from .rendering import _compose_reference_image, _frame_to_image
from .session_state import OrigamiSession

if TYPE_CHECKING:
    from .recording import OvershootInputRecorder

logger = logging.getLogger("uvicorn.error")

# aiortc does not expose sender bitrate parameters; tune the H.264 codec module
# before any backend-originated demo or Overshoot encoders are created.
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


class ReferenceCompositeTrack(TimedVideoTrack):
    def __init__(
        self,
        manager: Any,
        session: OrigamiSession,
        recorder: OvershootInputRecorder | None = None,
    ) -> None:
        super().__init__(fps=OVERSHOOT_FPS)
        self._manager = manager
        self._session = session
        self._recorder = recorder
        self._last_frame_id: int | None = None

    async def recv(self) -> VideoFrame:
        item: tuple[int, VideoFrame] | None = None
        while item is None:
            await self._wait_tick()
            item = await self._session.camera_frames.wait_for_new(
                self._last_frame_id,
                timeout_seconds=0.2,
            )

        self._last_frame_id = item[0]
        camera = _frame_to_image(item[1], fallback_size=(1024, 768))
        if self._recorder is not None:
            self._recorder.record(camera)

        step = self._manager.current_step_for(self._session)
        reference = self._manager.reference_image_for(step)
        return self._video_frame_from_image(
            _compose_reference_image(camera, reference, "Reference shape")
        )


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


def create_overshoot_peer_connection() -> RTCPeerConnection:
    return RTCPeerConnection(
        RTCConfiguration(
            iceServers=[
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
                RTCIceServer(
                    urls=[
                        "turn:turn.overshoot.ai:3478?transport=udp",
                        "turn:turn.overshoot.ai:3478?transport=tcp",
                        "turns:turn.overshoot.ai:443?transport=udp",
                        "turns:turn.overshoot.ai:443?transport=tcp",
                    ],
                    username="overshoot",
                    credential="overshoot",
                ),
            ]
        )
    )
