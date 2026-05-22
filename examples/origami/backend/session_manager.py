from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import httpx
import websockets
from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCRtpReceiver,
    RTCRtpSender,
    RTCSessionDescription,
)
from aiortc.codecs import h264 as aiortc_h264
from aiortc.rtcdatachannel import RTCDataChannel
from av import VideoFrame
from fastapi import HTTPException
from origami_config import OrigamiStep, load_origami_steps
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from websockets import ConnectionClosed

logger = logging.getLogger("uvicorn.error")

DEFAULT_OVERSHOOT_API_URL = "https://api.overshoot.ai/v0.2"
DEFAULT_OVERSHOOT_MODEL = "Qwen/Qwen3.6-27B-FP8"
DEFAULT_OVERSHOOT_MODE = "frame"
DEFAULT_OVERSHOOT_PROCESSING = {"interval_seconds": 0.5}
BOOLEAN_OUTPUT_SCHEMA = {"type": "boolean"}

PHASE_WAITING = "WAITING_FOR_START"
PHASE_GUIDING = "GUIDING"
PHASE_STEP_DONE = "STEP_DONE"
PHASE_COMPLETED = "COMPLETED"
PHASE_ERROR = "ERROR"

ANDROID_CHANNEL_LABEL = "session-events"
DEMO_CHANNEL_LABEL = "demo-events"
OVERSHOOT_WS_MAX_RECONNECT_ATTEMPTS = 8
OVERSHOOT_WS_RETRY_BASE_SECONDS = 1.0
OVERSHOOT_WS_RETRY_MAX_SECONDS = 15.0
OVERSHOOT_WS_STREAM_ENDED_CLOSE_CODE = 1001
OVERSHOOT_WS_AUTH_FAILURE_CLOSE_CODE = 1008
VIDEO_CLOCK_RATE = 90_000
DEMO_FPS = 5
OVERSHOOT_FPS = 5
AIORTC_H264_DEFAULT_BITRATE = 2_000_000
AIORTC_H264_MIN_BITRATE = 500_000
AIORTC_H264_MAX_BITRATE = 3_000_000
OVERSHOOT_STATS_LOG_INTERVAL_SECONDS = 5.0
DEBUG_COMPOSITE_INTERVAL_SECONDS = 1.0
OVERSHOOT_STEP_RESULT_GRACE_SECONDS = 0.6
DEMO_BACKGROUND_BRIGHTNESS = 0.68
HUD_WIDTH = 480
HUD_HEIGHT = 640
HUD_GREEN = (0, 255, 96)
HUD_DIM_GREEN = (28, 190, 82)
HUD_DENSITY = 1.5

__all__ = [
    "DEFAULT_OVERSHOOT_API_URL",
    "DEFAULT_OVERSHOOT_MODEL",
    "OrigamiSessionManager",
]

# aiortc does not expose sender bitrate parameters; tune the H.264 codec module
# before any backend-originated demo or Overshoot encoders are created.
setattr(aiortc_h264, "DEFAULT_BITRATE", AIORTC_H264_DEFAULT_BITRATE)
setattr(aiortc_h264, "MIN_BITRATE", AIORTC_H264_MIN_BITRATE)
setattr(aiortc_h264, "MAX_BITRATE", AIORTC_H264_MAX_BITRATE)


@dataclass
class SessionEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class LatestFrameBuffer:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._latest: tuple[int, VideoFrame] | None = None
        self._counter = 0
        self._closed = False

    async def update(self, frame: VideoFrame) -> None:
        async with self._condition:
            if self._closed:
                return
            self._counter += 1
            self._latest = (self._counter, frame)
            self._condition.notify_all()

    async def latest(self) -> tuple[int, VideoFrame] | None:
        async with self._condition:
            return self._latest

    async def wait_for_new(
        self,
        last_id: int | None,
        *,
        timeout_seconds: float,
    ) -> tuple[int, VideoFrame] | None:
        deadline = time.monotonic() + timeout_seconds
        async with self._condition:
            while not self._closed:
                if self._latest is not None and (
                    last_id is None or self._latest[0] != last_id
                ):
                    return self._latest
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._latest
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except TimeoutError:
                    return self._latest
            return None

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


@dataclass
class OrigamiSession:
    session_id: str
    queue: asyncio.Queue[SessionEvent] = field(default_factory=asyncio.Queue)
    loop_task: asyncio.Task[None] | None = None
    media_pc: RTCPeerConnection | None = None
    data_channel: RTCDataChannel | None = None
    phase: str = PHASE_WAITING
    step_index: int = 0
    auto_check_enabled: bool = True
    true_streak: int = 0
    destroyed: bool = False
    track_counter: int = 0
    camera_frames: LatestFrameBuffer = field(default_factory=LatestFrameBuffer)
    track_tasks: list[asyncio.Task[None]] = field(default_factory=list)
    done_task: asyncio.Task[None] | None = None
    overshoot_generation: int = 0
    overshoot_pc: RTCPeerConnection | None = None
    overshoot_stream_id: str | None = None
    overshoot_lease_ttl_seconds: int | None = None
    overshoot_ws_task: asyncio.Task[None] | None = None
    overshoot_keepalive_task: asyncio.Task[None] | None = None
    overshoot_stats_task: asyncio.Task[None] | None = None
    active_prompt_text: str | None = None
    guiding_step_started_at: float = 0.0
    overshoot_ignore_results_until: float = 0.0
    last_debug_composite_save_at: float = 0.0


@dataclass
class DemoViewer:
    viewer_id: str
    pc: RTCPeerConnection
    data_channel: RTCDataChannel | None = None


class OrigamiSessionManager:
    def __init__(
        self,
        *,
        overshoot_api_url: str,
        overshoot_api_key: str,
        overshoot_model: str,
        steps_path: Path,
        auto_check_available: bool = True,
        save_overshoot_composites: bool = False,
        debug_composite_dir: Path | None = None,
    ) -> None:
        self._overshoot_api_url = overshoot_api_url.rstrip("/")
        self._overshoot_api_key = overshoot_api_key
        self._overshoot_model = overshoot_model
        self._auto_check_available = auto_check_available
        self._save_overshoot_composites = save_overshoot_composites
        self._debug_composite_dir = (
            debug_composite_dir
            if debug_composite_dir is not None
            else steps_path.parent.parent / "debug" / "overshoot-composites"
        )
        self._steps = load_origami_steps(steps_path)
        self._reference_images = self._load_reference_images(self._steps)
        self._hud_images = self._load_hud_images(self._steps, steps_path.parent)
        self._overshoot_http = httpx.AsyncClient(
            base_url=self._overshoot_api_url,
            timeout=httpx.Timeout(20.0),
            headers={"Authorization": f"Bearer {self._overshoot_api_key}"},
        )
        self._sessions: dict[str, OrigamiSession] = {}
        self._viewers: dict[str, DemoViewer] = {}
        self._sessions_lock = asyncio.Lock()
        self._viewers_lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._sessions_lock:
            session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            await self.destroy_session(session_id, reason="server shutdown")

        async with self._viewers_lock:
            viewers = list(self._viewers.values())
            self._viewers.clear()
        for viewer in viewers:
            await viewer.pc.close()

        await self._overshoot_http.aclose()

    async def create_media_session(self, offer_sdp: str) -> dict[str, str]:
        offer_sdp = offer_sdp.strip()
        if not offer_sdp:
            raise HTTPException(status_code=422, detail="offer_sdp must not be empty")

        session_id = str(uuid.uuid4())
        session = OrigamiSession(session_id=session_id)
        pc = self._create_peer_connection()
        session.media_pc = pc

        @pc.on("connectionstatechange")
        async def on_connection_state_change() -> None:
            logger.info("session=%s media state=%s", session_id, pc.connectionState)
            if pc.connectionState in {"failed", "closed"}:
                await self.destroy_session(session_id, reason=pc.connectionState)

        @pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel) -> None:
            logger.info(
                "session=%s android data channel opened label=%s",
                session_id,
                channel.label,
            )
            self._attach_android_channel(session, channel)

        @pc.on("track")
        def on_track(track: MediaStreamTrack) -> None:
            if track.kind != "video":
                logger.info("session=%s ignoring track kind=%s", session_id, track.kind)
                return
            track_kind = self._assign_track_kind(session, track)
            task = asyncio.create_task(
                self._consume_video_track(session, track, track_kind),
                name=f"{session_id}-{track_kind}-track",
            )
            session.track_tasks.append(task)

        try:
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=offer_sdp, type="offer")
            )
            for transceiver in pc.getTransceivers():
                if transceiver.kind == "video":
                    _prefer_codec(transceiver, "video/H264", sender=False)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            await _wait_for_ice_gathering_complete(pc)
        except Exception:
            await self._cleanup_session(session)
            raise

        await self.destroy_all_sessions("new media session requested")
        session.loop_task = asyncio.create_task(
            self._run_session_loop(session),
            name=f"origami-session-{session_id}",
        )
        async with self._sessions_lock:
            self._sessions[session_id] = session
        await self._broadcast_demo_state()

        return {
            "session_id": session_id,
            "answer_sdp": pc.localDescription.sdp,
        }

    async def create_demo_session(self, offer_sdp: str) -> dict[str, str]:
        offer_sdp = offer_sdp.strip()
        if not offer_sdp:
            raise HTTPException(status_code=422, detail="offer_sdp must not be empty")

        viewer_id = str(uuid.uuid4())
        pc = self._create_peer_connection()
        viewer = DemoViewer(viewer_id=viewer_id, pc=pc)

        async with self._viewers_lock:
            self._viewers[viewer_id] = viewer

        @pc.on("connectionstatechange")
        async def on_connection_state_change() -> None:
            logger.info("demo=%s media state=%s", viewer_id, pc.connectionState)
            if pc.connectionState in {"failed", "closed"}:
                await self.destroy_demo_viewer(viewer_id)

        @pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel) -> None:
            logger.info(
                "demo=%s data channel opened label=%s", viewer_id, channel.label
            )
            viewer.data_channel = channel
            self._attach_demo_channel(viewer, channel)

        try:
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=offer_sdp, type="offer")
            )
            pc.addTrack(DemoCompositeTrack(self))
            for transceiver in pc.getTransceivers():
                if transceiver.sender and transceiver.sender.track:
                    _prefer_codec(transceiver, "video/H264", sender=True)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            await _wait_for_ice_gathering_complete(pc)
        except Exception:
            await self.destroy_demo_viewer(viewer_id)
            raise

        return {
            "viewer_id": viewer_id,
            "answer_sdp": pc.localDescription.sdp,
        }

    async def destroy_demo_viewer(self, viewer_id: str) -> None:
        async with self._viewers_lock:
            viewer = self._viewers.pop(viewer_id, None)
        if viewer is not None:
            await viewer.pc.close()

    async def destroy_all_sessions(self, reason: str) -> None:
        async with self._sessions_lock:
            session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            await self.destroy_session(session_id, reason=reason)

    async def destroy_session(self, session_id: str, reason: str) -> None:
        async with self._sessions_lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return
        session.destroyed = True
        await session.queue.put(
            SessionEvent(kind="session.destroy", payload={"reason": reason})
        )
        if session.loop_task is not None:
            with suppress(Exception):
                await session.loop_task
        await self._broadcast_demo_state()

    async def demo_frame_image(self) -> Image.Image:
        session = await self._latest_session()
        if session is None:
            hud_state = _empty_hud_payload(self._auto_check_available)
            return _compose_demo_image(
                base=_demo_placeholder("Waiting for glasses"),
                hud_state=hud_state,
                hud_image=self.hud_image_for(self._steps[0]),
            )

        camera_item = await session.camera_frames.latest()
        hud_state = self._hud_payload(session)

        if camera_item is None:
            base = _demo_placeholder("Waiting for camera")
        else:
            base = _frame_to_image(camera_item[1], fallback_size=(1024, 768))
        return _compose_demo_image(
            base=base,
            hud_state=hud_state,
            hud_image=self.hud_image_for(self.current_step_for(session)),
        )

    async def _latest_session(self) -> OrigamiSession | None:
        async with self._sessions_lock:
            sessions = list(self._sessions.values())
        if not sessions:
            return None
        return sessions[-1]

    def _attach_android_channel(
        self,
        session: OrigamiSession,
        channel: RTCDataChannel,
    ) -> None:
        session.data_channel = channel

        @channel.on("open")
        def on_open() -> None:
            self._send_channel_json(
                channel,
                {"type": "session.ready", "session_id": session.session_id},
            )
            self._send_channel_json(channel, self._hud_payload(session))

        @channel.on("message")
        def on_message(message: Any) -> None:
            if isinstance(message, str):
                asyncio.create_task(self._handle_channel_message(session, message))
            else:
                logger.info(
                    "session=%s ignoring binary data channel message",
                    session.session_id,
                )

        @channel.on("close")
        def on_close() -> None:
            if session.data_channel is channel:
                session.data_channel = None

        if channel.readyState == "open":
            on_open()

    def _attach_demo_channel(self, viewer: DemoViewer, channel: RTCDataChannel) -> None:
        @channel.on("open")
        def on_open() -> None:
            asyncio.create_task(self._send_demo_initial_state(channel))

        @channel.on("message")
        def on_message(message: Any) -> None:
            if isinstance(message, str):
                asyncio.create_task(self._handle_demo_message(message))

        @channel.on("close")
        def on_close() -> None:
            if viewer.data_channel is channel:
                viewer.data_channel = None

        if channel.readyState == "open":
            on_open()

    async def _send_demo_initial_state(self, channel: RTCDataChannel) -> None:
        session = await self._latest_session()
        payload = (
            {
                "type": "demo.state",
                "message": "Waiting for glasses",
                "auto_check_available": self._auto_check_available,
            }
            if session is None
            else self._hud_payload(session)
        )
        self._send_channel_json(channel, payload)

    async def _handle_channel_message(
        self,
        session: OrigamiSession,
        raw_text: str,
    ) -> None:
        payload = _parse_json_object(raw_text)
        if payload is None:
            return
        message_type = str(payload.get("type") or "").strip()
        if not message_type:
            return
        await session.queue.put(SessionEvent(kind=message_type, payload=payload))

    async def _handle_demo_message(self, raw_text: str) -> None:
        payload = _parse_json_object(raw_text)
        if payload is None:
            return
        session = await self._latest_session()
        if session is None:
            await self._broadcast_demo_json(
                {"type": "demo.state", "message": "No glasses session is connected."}
            )
            return
        message_type = str(payload.get("type") or "").strip()
        if not message_type:
            return
        await session.queue.put(SessionEvent(kind=message_type, payload=payload))

    async def _run_session_loop(self, session: OrigamiSession) -> None:
        while True:
            event = await session.queue.get()
            if event.kind == "session.destroy":
                await self._cleanup_session(session)
                return
            try:
                await self._handle_event(session, event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "session=%s event=%s failed", session.session_id, event.kind
                )
                await self._fail_session(
                    session, "Something went wrong. Double tap to restart."
                )

    async def _handle_event(self, session: OrigamiSession, event: SessionEvent) -> None:
        if event.kind == "session.start":
            await self._start_guidance(session)
            return
        if event.kind == "session.reset":
            await self._reset_to_waiting(session)
            return
        if event.kind == "manual.next":
            await self._manual_move(session, delta=1)
            return
        if event.kind == "manual.prev":
            await self._manual_move(session, delta=-1)
            return
        if event.kind == "auto.toggle":
            await self._toggle_auto_check(session)
            return
        if event.kind == "client.media_ready":
            await self._publish_hud_state(session)
            return
        if event.kind == "camera.frame":
            await self._maybe_save_overshoot_debug_composite(session)
            if session.phase == PHASE_GUIDING and session.auto_check_enabled:
                await self._sync_overshoot_for_current_step(session)
            return
        if event.kind == "overshoot.result":
            await self._handle_overshoot_result(session, event.payload)
            return
        if event.kind == "overshoot.closed":
            await self._handle_overshoot_closed(session, event.payload)
            return
        if event.kind == "auto.advance":
            await self._auto_advance_after_done(session, event.payload)

    async def _start_guidance(self, session: OrigamiSession) -> None:
        if session.phase not in {PHASE_WAITING, PHASE_COMPLETED, PHASE_ERROR}:
            return
        await self._cancel_done_task(session)
        session.phase = PHASE_GUIDING
        session.step_index = 0
        session.true_streak = 0
        session.auto_check_enabled = self._auto_check_available
        self._mark_guiding_step_started(session)
        await self._publish_hud_state(session)
        await self._sync_overshoot_for_current_step(session)

    async def _reset_to_waiting(self, session: OrigamiSession) -> None:
        await self._cancel_done_task(session)
        await self._stop_overshoot_runtime(session)
        session.phase = PHASE_WAITING
        session.step_index = 0
        session.true_streak = 0
        session.auto_check_enabled = self._auto_check_available
        session.active_prompt_text = None
        session.guiding_step_started_at = 0.0
        session.overshoot_ignore_results_until = 0.0
        await self._publish_hud_state(session)

    async def _manual_move(self, session: OrigamiSession, *, delta: int) -> None:
        if session.phase == PHASE_WAITING:
            return
        await self._cancel_done_task(session)
        step_count = len(self._steps)

        if delta > 0:
            if session.step_index >= step_count - 1:
                session.phase = PHASE_COMPLETED
                session.true_streak = 0
                await self._stop_overshoot_runtime(session)
                await self._publish_hud_state(session)
                return
            session.step_index += 1
        else:
            if session.phase == PHASE_COMPLETED:
                session.step_index = step_count - 1
            else:
                session.step_index = max(0, session.step_index - 1)

        session.phase = PHASE_GUIDING
        session.true_streak = 0
        self._mark_guiding_step_started(session)
        await self._publish_hud_state(session)
        await self._sync_overshoot_for_current_step(session)

    async def _toggle_auto_check(self, session: OrigamiSession) -> None:
        if session.phase not in {PHASE_GUIDING, PHASE_STEP_DONE}:
            return
        if not self._auto_check_available:
            session.auto_check_enabled = False
            await self._stop_overshoot_runtime(session)
            await self._publish_hud_state(session)
            return
        session.auto_check_enabled = not session.auto_check_enabled
        session.true_streak = 0
        if session.auto_check_enabled and session.phase == PHASE_GUIDING:
            await self._sync_overshoot_for_current_step(session)
        else:
            await self._stop_overshoot_runtime(session)
        await self._publish_hud_state(session)

    async def _handle_overshoot_result(
        self,
        session: OrigamiSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.overshoot_generation:
            return
        if session.phase != PHASE_GUIDING or not session.auto_check_enabled:
            return

        received_at = _payload_received_at(payload)
        if received_at < session.guiding_step_started_at:
            logger.info(
                "session=%s ignoring overshoot result received before current step",
                session.session_id,
            )
            return
        if received_at < session.overshoot_ignore_results_until:
            logger.info(
                "session=%s ignoring overshoot result during step settle window",
                session.session_id,
            )
            return

        prompt = str(payload.get("prompt") or "")
        if (
            prompt
            and session.active_prompt_text
            and not prompt.startswith(session.active_prompt_text)
        ):
            logger.info(
                "session=%s ignoring result for stale prompt",
                session.session_id,
            )
            return

        observed = _parse_overshoot_boolean(payload)
        if observed is None:
            logger.info(
                "session=%s ignoring non-boolean overshoot payload=%s",
                session.session_id,
                _compact_json(payload),
            )
            return

        if observed:
            session.true_streak += 1
        else:
            session.true_streak = 0

        logger.info(
            "session=%s step=%s overshoot observed=%s streak=%s",
            session.session_id,
            session.step_index + 1,
            observed,
            session.true_streak,
        )

        if session.true_streak >= 2:
            await self._mark_step_done(session)
        else:
            await self._publish_hud_state(session)

    async def _mark_step_done(self, session: OrigamiSession) -> None:
        await self._cancel_done_task(session)
        session.phase = PHASE_STEP_DONE
        session.true_streak = 0
        await self._publish_hud_state(session)
        step_index = session.step_index
        session.done_task = asyncio.create_task(
            self._queue_delayed_auto_advance(session, step_index),
            name=f"origami-done-delay-{session.session_id}",
        )

    async def _queue_delayed_auto_advance(
        self,
        session: OrigamiSession,
        step_index: int,
    ) -> None:
        try:
            await asyncio.sleep(2.0)
            await session.queue.put(
                SessionEvent(
                    kind="auto.advance",
                    payload={"step_index": step_index},
                )
            )
        except asyncio.CancelledError:
            raise

    async def _auto_advance_after_done(
        self,
        session: OrigamiSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("step_index") != session.step_index:
            return
        if session.phase != PHASE_STEP_DONE:
            return

        session.done_task = None
        if session.step_index >= len(self._steps) - 1:
            session.phase = PHASE_COMPLETED
            await self._stop_overshoot_runtime(session)
            await self._publish_hud_state(session)
            return

        session.step_index += 1
        session.phase = PHASE_GUIDING
        session.true_streak = 0
        self._mark_guiding_step_started(session)
        await self._publish_hud_state(session)
        await self._sync_overshoot_for_current_step(session)

    async def _handle_overshoot_closed(
        self,
        session: OrigamiSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.overshoot_generation:
            return
        if session.phase in {PHASE_WAITING, PHASE_COMPLETED, PHASE_ERROR}:
            return
        if not self._auto_check_available:
            return
        if not session.auto_check_enabled:
            return
        await self._fail_session(
            session, "Overshoot stream ended. Double tap to restart."
        )

    async def _fail_session(self, session: OrigamiSession, message: str) -> None:
        await self._cancel_done_task(session)
        await self._stop_overshoot_runtime(session)
        session.phase = PHASE_ERROR
        session.true_streak = 0
        self._send_session_json(session, {"type": "hud.error", "message": message})
        await self._publish_hud_state(session)

    async def _publish_hud_state(self, session: OrigamiSession) -> None:
        payload = self._hud_payload(session)
        self._send_session_json(session, payload)
        await self._broadcast_demo_json(payload)

    def _hud_payload(self, session: OrigamiSession) -> dict[str, Any]:
        step = self._steps[min(session.step_index, len(self._steps) - 1)]
        screen = "start" if session.phase == PHASE_WAITING else "running"
        message = ""
        if session.phase == PHASE_STEP_DONE:
            message = "Done! Next step..."
        elif session.phase == PHASE_COMPLETED:
            message = "Complete. Double tap to reset."
        elif session.phase == PHASE_ERROR:
            message = "Error. Double tap to reset."
        return {
            "type": "hud.state",
            "screen": screen,
            "phase": session.phase,
            "step_index": session.step_index,
            "step_number": session.step_index + 1,
            "step_count": len(self._steps),
            "step_id": step.id,
            "step_title": step.title,
            "hud_image": step.hud_image,
            "auto_check_enabled": (
                session.auto_check_enabled and self._auto_check_available
            ),
            "auto_check_available": self._auto_check_available,
            "true_streak": session.true_streak,
            "message": message,
        }

    def _send_session_json(
        self, session: OrigamiSession, payload: dict[str, Any]
    ) -> None:
        channel = session.data_channel
        if channel is not None:
            self._send_channel_json(channel, payload)

    async def _broadcast_demo_state(self) -> None:
        session = await self._latest_session()
        if session is None:
            await self._broadcast_demo_json(
                {
                    "type": "demo.state",
                    "message": "Waiting for glasses",
                    "auto_check_available": self._auto_check_available,
                }
            )
        else:
            await self._broadcast_demo_json(self._hud_payload(session))

    async def _broadcast_demo_json(self, payload: dict[str, Any]) -> None:
        async with self._viewers_lock:
            channels = [
                viewer.data_channel
                for viewer in self._viewers.values()
                if viewer.data_channel is not None
            ]
        for channel in channels:
            self._send_channel_json(channel, payload)

    def _send_channel_json(
        self,
        channel: RTCDataChannel,
        payload: dict[str, Any],
    ) -> None:
        if channel.readyState != "open":
            return
        try:
            channel.send(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
        except Exception:
            logger.exception("failed to send data channel message")

    def _assign_track_kind(
        self, session: OrigamiSession, track: MediaStreamTrack
    ) -> str:
        track_id = str(getattr(track, "id", "") or "").lower()
        if "camera" in track_id or "video0" in track_id:
            return "camera"
        session.track_counter += 1
        return "camera"

    async def _consume_video_track(
        self,
        session: OrigamiSession,
        track: MediaStreamTrack,
        track_kind: str,
    ) -> None:
        logger.info("session=%s %s track started", session.session_id, track_kind)
        try:
            while True:
                frame = await track.recv()
                if not isinstance(frame, VideoFrame):
                    continue
                await session.camera_frames.update(frame)
                await session.queue.put(SessionEvent(kind="camera.frame"))
        except Exception:
            logger.info("session=%s %s track ended", session.session_id, track_kind)

    def _mark_guiding_step_started(self, session: OrigamiSession) -> None:
        now = time.monotonic()
        session.guiding_step_started_at = now
        session.overshoot_ignore_results_until = (
            now + OVERSHOOT_STEP_RESULT_GRACE_SECONDS
        )

    async def _sync_overshoot_for_current_step(self, session: OrigamiSession) -> None:
        if not self._auto_check_available:
            return
        if session.phase != PHASE_GUIDING or not session.auto_check_enabled:
            return

        if session.overshoot_stream_id is None or session.overshoot_pc is None:
            if (
                session.overshoot_stream_id is not None
                or session.overshoot_pc is not None
            ):
                await self._stop_overshoot_runtime(session)
            await self._start_overshoot_runtime(session)
            return

        step = self.current_step_for(session)
        await self._switch_overshoot_prompt(session, step.prompt)

    async def _switch_overshoot_prompt(
        self,
        session: OrigamiSession,
        prompt: str,
    ) -> None:
        if session.active_prompt_text == prompt:
            return
        stream_id = session.overshoot_stream_id
        if stream_id is None:
            session.active_prompt_text = prompt
            return

        response = await self._overshoot_http.patch(
            f"/streams/{stream_id}/config/prompt",
            json={"prompt": prompt},
        )
        if not response.is_success:
            raise RuntimeError(
                "Failed to update Overshoot prompt "
                f"(HTTP {response.status_code}): {_response_text(response)}"
            )

        session.active_prompt_text = prompt
        logger.info(
            "session=%s overshoot prompt switched step=%s",
            session.session_id,
            session.step_index + 1,
        )

    async def _maybe_save_overshoot_debug_composite(
        self, session: OrigamiSession
    ) -> None:
        if not self._save_overshoot_composites:
            return
        if session.phase != PHASE_GUIDING:
            return

        now = time.monotonic()
        if (
            now - session.last_debug_composite_save_at
            < DEBUG_COMPOSITE_INTERVAL_SECONDS
        ):
            return
        session.last_debug_composite_save_at = now

        camera_item = await session.camera_frames.latest()
        if camera_item is None:
            return

        step = self.current_step_for(session)
        camera = _frame_to_image(camera_item[1], fallback_size=(1024, 768))
        reference = self.reference_image_for(step)
        image = _compose_reference_image(camera, reference, "Reference shape")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self._debug_composite_dir / (
            f"{timestamp}_step-{session.step_index + 1:02d}_"
            f"{session.session_id[:8]}.jpg"
        )
        try:
            await asyncio.to_thread(_save_jpeg, image, path)
        except Exception:
            logger.exception("failed to save Overshoot debug composite to %s", path)

    async def _start_overshoot_runtime(self, session: OrigamiSession) -> None:
        step = self._steps[session.step_index]
        generation = session.overshoot_generation + 1
        session.overshoot_generation = generation
        session.active_prompt_text = step.prompt

        pc = self._create_overshoot_peer_connection()

        @pc.on("connectionstatechange")
        def on_connection_state_change() -> None:
            logger.info(
                "session=%s overshoot media state=%s generation=%s",
                session.session_id,
                pc.connectionState,
                generation,
            )

        @pc.on("iceconnectionstatechange")
        def on_ice_connection_state_change() -> None:
            logger.info(
                "session=%s overshoot ice state=%s generation=%s",
                session.session_id,
                pc.iceConnectionState,
                generation,
            )

        session.overshoot_pc = pc
        created_stream_id: str | None = None
        pc.addTrack(ReferenceCompositeTrack(self, session))
        for transceiver in pc.getTransceivers():
            if transceiver.sender and transceiver.sender.track:
                _prefer_codec(transceiver, "video/H264", sender=True)

        try:
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            await _wait_for_ice_gathering_complete(pc)
            local_sdp = pc.localDescription.sdp

            payload = {
                "source": {"type": "webrtc", "sdp": local_sdp},
                "mode": DEFAULT_OVERSHOOT_MODE,
                "processing": DEFAULT_OVERSHOOT_PROCESSING,
                "inference": {
                    "prompt": step.prompt,
                    "backend": "overshoot",
                    "model": self._overshoot_model,
                    "output_schema_json": BOOLEAN_OUTPUT_SCHEMA,
                },
            }
            response = await self._overshoot_http.post("/streams", json=payload)
            if not response.is_success:
                raise RuntimeError(
                    "Failed to create Overshoot stream "
                    f"(HTTP {response.status_code}): {_response_text(response)}"
                )

            data = response.json()
            stream_id = str(data.get("stream_id") or "").strip()
            created_stream_id = stream_id or None
            answer_sdp = _extract_answer_sdp(data.get("webrtc"))
            ttl_seconds = _parse_positive_int(
                (data.get("lease") or {}).get("ttl_seconds")
            )
            if not stream_id or not answer_sdp.startswith("v="):
                if stream_id:
                    await self._close_overshoot_stream(stream_id)
                raise RuntimeError("Overshoot response missing stream id or answer SDP")

            current = await self._get_session_if_current(
                session.session_id,
                generation,
            )
            if current is None:
                await self._close_overshoot_stream(stream_id)
                return

            current.overshoot_stream_id = stream_id
            current.overshoot_lease_ttl_seconds = ttl_seconds
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer_sdp, type="answer")
            )
            current.overshoot_ws_task = asyncio.create_task(
                self._run_overshoot_ws(current.session_id, stream_id, generation),
                name=f"overshoot-ws-{current.session_id}-{generation}",
            )
            if ttl_seconds:
                current.overshoot_keepalive_task = asyncio.create_task(
                    self._run_overshoot_keepalive(
                        current.session_id,
                        stream_id,
                        ttl_seconds,
                        generation,
                    ),
                    name=f"overshoot-keepalive-{current.session_id}-{generation}",
                )
            current.overshoot_stats_task = asyncio.create_task(
                self._run_overshoot_stats_logger(
                    current.session_id,
                    generation,
                    pc,
                ),
                name=f"overshoot-stats-{current.session_id}-{generation}",
            )
            logger.info(
                "session=%s overshoot started step=%s stream_id=%s generation=%s",
                current.session_id,
                current.step_index + 1,
                stream_id,
                generation,
            )
        except Exception:
            if created_stream_id and session.overshoot_stream_id != created_stream_id:
                await self._close_overshoot_stream(created_stream_id)
            await self._stop_overshoot_runtime(session)
            raise

    async def _stop_overshoot_runtime(self, session: OrigamiSession) -> None:
        session.overshoot_generation += 1
        stream_id = session.overshoot_stream_id
        pc = session.overshoot_pc
        session.overshoot_stream_id = None
        session.overshoot_lease_ttl_seconds = None
        session.overshoot_pc = None
        tasks: list[asyncio.Task[None]] = []
        for task in (
            session.overshoot_ws_task,
            session.overshoot_keepalive_task,
            session.overshoot_stats_task,
        ):
            if task is not None:
                task.cancel()
                tasks.append(task)
        session.overshoot_ws_task = None
        session.overshoot_keepalive_task = None
        session.overshoot_stats_task = None
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if pc is not None:
            await pc.close()
        if stream_id:
            await self._close_overshoot_stream(stream_id)

    async def _run_overshoot_stats_logger(
        self,
        session_id: str,
        generation: int,
        pc: RTCPeerConnection,
    ) -> None:
        previous_bytes: int | None = None
        previous_packets: int | None = None
        previous_time: float | None = None

        try:
            while True:
                await asyncio.sleep(OVERSHOOT_STATS_LOG_INTERVAL_SECONDS)
                session = await self._get_session_if_current(session_id, generation)
                if session is None or session.overshoot_pc is not pc:
                    return

                try:
                    stats = await pc.getStats()
                except Exception as error:
                    logger.warning(
                        "session=%s overshoot stats unavailable error=%s",
                        session_id,
                        error,
                    )
                    continue

                outbound = _find_stats(stats.values(), "outbound-rtp", "video")
                remote_inbound = _find_stats(
                    stats.values(), "remote-inbound-rtp", "video"
                )
                transport = _find_stats(stats.values(), "transport", None)
                if outbound is None:
                    logger.info(
                        "session=%s overshoot stats unavailable generation=%s",
                        session_id,
                        generation,
                    )
                    continue

                now = time.monotonic()
                bytes_sent = _stats_int(outbound, "bytesSent")
                packets_sent = _stats_int(outbound, "packetsSent")
                bitrate_bps: float | None = None
                packet_delta: int | None = None
                if previous_bytes is not None and previous_time is not None:
                    elapsed = now - previous_time
                    byte_delta = bytes_sent - previous_bytes
                    packet_delta = packets_sent - (previous_packets or 0)
                    if elapsed > 0 and byte_delta >= 0:
                        bitrate_bps = byte_delta * 8 / elapsed
                previous_bytes = bytes_sent
                previous_packets = packets_sent
                previous_time = now

                rtt_seconds = _stats_float(remote_inbound, "roundTripTime")
                fraction_lost = _stats_float(remote_inbound, "fractionLost")
                packets_lost = _stats_int(remote_inbound, "packetsLost")
                transport_state = _stats_text(transport, "dtlsState")
                ice_role = _stats_text(transport, "iceRole")

                logger.info(
                    "session=%s overshoot outbound stats generation=%s "
                    "bitrate_kbps=%s packets_sent=%s packet_delta=%s "
                    "bytes_sent=%s rtt_ms=%s loss_pct=%s packets_lost=%s "
                    "transport=%s/%s",
                    session_id,
                    generation,
                    _format_kbps(bitrate_bps),
                    packets_sent,
                    _format_optional_int(packet_delta),
                    bytes_sent,
                    _format_ms(rtt_seconds),
                    _format_rtcp_loss_pct(fraction_lost),
                    packets_lost,
                    transport_state,
                    ice_role,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s overshoot stats logger crashed", session_id)

    async def _run_overshoot_keepalive(
        self,
        session_id: str,
        stream_id: str,
        ttl_seconds: int,
        generation: int,
    ) -> None:
        interval_seconds = max(ttl_seconds / 2.0, 5.0)
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                session = await self._get_session_if_current(session_id, generation)
                if session is None:
                    return
                response = await self._overshoot_http.post(
                    f"/streams/{stream_id}/keepalive"
                )
                if not response.is_success:
                    logger.error(
                        "session=%s keepalive failed status=%s body=%s",
                        session_id,
                        response.status_code,
                        _response_text(response),
                    )
                    await session.queue.put(
                        SessionEvent(
                            kind="overshoot.closed",
                            payload={
                                "generation": generation,
                                "reason": "keepalive_failed",
                            },
                        )
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s keepalive crashed", session_id)

    async def _run_overshoot_ws(
        self,
        session_id: str,
        stream_id: str,
        generation: int,
    ) -> None:
        ws_base = self._overshoot_api_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        ws_url = f"{ws_base}/ws/streams/{stream_id}"
        attempt = 0
        while True:
            session = await self._get_session_if_current(session_id, generation)
            if session is None:
                return
            try:
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as overshoot_ws:
                    await overshoot_ws.send(
                        json.dumps({"api_key": self._overshoot_api_key})
                    )
                    async for raw_message in overshoot_ws:
                        raw_text = (
                            raw_message.decode()
                            if isinstance(raw_message, bytes)
                            else raw_message
                        )
                        payload = _parse_json_object(raw_text)
                        if payload is None:
                            logger.info(
                                "session=%s overshoot bad json=%s", session_id, raw_text
                            )
                            continue
                        current = await self._get_session_if_current(
                            session_id, generation
                        )
                        if current is None:
                            return
                        logger.info(
                            "session=%s overshoot payload=%s",
                            session_id,
                            _compact_json(_overshoot_payload_for_log(payload)),
                        )
                        await current.queue.put(
                            SessionEvent(
                                kind="overshoot.result",
                                payload={
                                    "generation": generation,
                                    "_received_at": time.monotonic(),
                                    **payload,
                                },
                            )
                        )
                        attempt = 0
                    if (
                        overshoot_ws.close_code == OVERSHOOT_WS_STREAM_ENDED_CLOSE_CODE
                        and overshoot_ws.close_reason
                    ):
                        await self._notify_overshoot_closed(
                            session_id,
                            generation,
                            overshoot_ws.close_reason,
                        )
                        return
                    logger.warning(
                        "session=%s overshoot websocket closed code=%s reason=%s",
                        session_id,
                        overshoot_ws.close_code,
                        overshoot_ws.close_reason,
                    )
            except asyncio.CancelledError:
                raise
            except ConnectionClosed as exc:
                if exc.code == OVERSHOOT_WS_AUTH_FAILURE_CLOSE_CODE:
                    await self._notify_overshoot_closed(
                        session_id,
                        generation,
                        exc.reason or "authentication_failed",
                    )
                    return
                if exc.code == OVERSHOOT_WS_STREAM_ENDED_CLOSE_CODE and exc.reason:
                    await self._notify_overshoot_closed(
                        session_id, generation, exc.reason
                    )
                    return
                logger.warning(
                    "session=%s overshoot websocket closed code=%s reason=%s",
                    session_id,
                    exc.code,
                    exc.reason,
                )
            except Exception:
                logger.exception("session=%s overshoot websocket crashed", session_id)

            attempt += 1
            if attempt > OVERSHOOT_WS_MAX_RECONNECT_ATTEMPTS:
                await self._notify_overshoot_closed(
                    session_id,
                    generation,
                    "reconnect_exhausted",
                )
                return
            delay = min(
                OVERSHOOT_WS_RETRY_MAX_SECONDS,
                OVERSHOOT_WS_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
            )
            await asyncio.sleep(delay)

    async def _notify_overshoot_closed(
        self,
        session_id: str,
        generation: int,
        reason: str | None,
    ) -> None:
        session = await self._get_session_if_current(session_id, generation)
        if session is None:
            return
        await session.queue.put(
            SessionEvent(
                kind="overshoot.closed",
                payload={"generation": generation, "reason": reason},
            )
        )

    async def _get_session_if_current(
        self,
        session_id: str,
        generation: int,
    ) -> OrigamiSession | None:
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None or session.destroyed:
            return None
        if session.overshoot_generation != generation:
            return None
        return session

    async def _close_overshoot_stream(self, stream_id: str) -> None:
        try:
            response = await self._overshoot_http.delete(f"/streams/{stream_id}")
        except httpx.HTTPError as error:
            logger.warning("stream=%s close failed error=%s", stream_id, error)
            return
        if not response.is_success and response.status_code != 404:
            logger.warning(
                "stream=%s close failed status=%s body=%s",
                stream_id,
                response.status_code,
                _response_text(response),
            )

    async def _cancel_done_task(self, session: OrigamiSession) -> None:
        if session.done_task is None:
            return
        session.done_task.cancel()
        with suppress(asyncio.CancelledError):
            await session.done_task
        session.done_task = None

    async def _cleanup_session(self, session: OrigamiSession) -> None:
        await self._cancel_done_task(session)
        await self._stop_overshoot_runtime(session)
        for task in session.track_tasks:
            task.cancel()
        if session.track_tasks:
            await asyncio.gather(*session.track_tasks, return_exceptions=True)
        await session.camera_frames.close()
        if session.media_pc is not None:
            await session.media_pc.close()
            session.media_pc = None

    def _create_peer_connection(self) -> RTCPeerConnection:
        return RTCPeerConnection(
            RTCConfiguration(
                iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
            )
        )

    def _create_overshoot_peer_connection(self) -> RTCPeerConnection:
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

    @staticmethod
    def _load_reference_images(steps: list[OrigamiStep]) -> dict[str, Image.Image]:
        images: dict[str, Image.Image] = {}
        for step in steps:
            with Image.open(step.reference_path) as image:
                images[step.id] = image.convert("RGB")
        return images

    @staticmethod
    def _load_hud_images(
        steps: list[OrigamiStep], asset_dir: Path
    ) -> dict[str, Image.Image]:
        images: dict[str, Image.Image] = {}
        step_image_dir = asset_dir / "step-imgs"
        for step in steps:
            path = step_image_dir / f"{step.hud_image}.png"
            if not path.exists():
                logger.warning("HUD step image not found: %s", path)
                continue
            with Image.open(path) as image:
                images[step.id] = image.convert("RGBA")
        return images

    def reference_image_for(self, step: OrigamiStep) -> Image.Image:
        return self._reference_images[step.id].copy()

    def hud_image_for(self, step: OrigamiStep) -> Image.Image | None:
        image = self._hud_images.get(step.id)
        return image.copy() if image is not None else None

    def current_step_for(self, session: OrigamiSession) -> OrigamiStep:
        return self._steps[min(session.step_index, len(self._steps) - 1)]


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
        manager: OrigamiSessionManager,
        session: OrigamiSession,
    ) -> None:
        super().__init__(fps=OVERSHOOT_FPS)
        self._manager = manager
        self._session = session
        self._last_frame_id: int | None = None

    async def recv(self) -> VideoFrame:
        await self._wait_tick()
        item = await self._session.camera_frames.wait_for_new(
            self._last_frame_id,
            timeout_seconds=0.2,
        )
        if item is not None:
            self._last_frame_id = item[0]
            camera = _frame_to_image(item[1], fallback_size=(1024, 768))
        else:
            camera = _demo_placeholder("Waiting for camera")
        step = self._manager.current_step_for(self._session)
        reference = self._manager.reference_image_for(step)
        return self._video_frame_from_image(
            _compose_reference_image(camera, reference, "Reference shape")
        )


class DemoCompositeTrack(TimedVideoTrack):
    def __init__(self, manager: OrigamiSessionManager) -> None:
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


def _compose_reference_image(
    camera: Image.Image,
    reference: Image.Image,
    label: str,
) -> Image.Image:
    base = camera.convert("RGB")
    width, height = base.size
    header_height = max(80, height // 4)
    reference_size = int(header_height * 0.75)
    margin = max(20, width // 24)
    gap = max(24, width // 20)

    header = Image.new("RGB", (width, header_height), "white")
    draw = ImageDraw.Draw(header)
    max_text_width = width - (2 * margin) - gap - reference_size
    font = _fit_font(draw, label, max_text_width, max(18, header_height // 3))
    bbox = draw.textbbox((0, 0), label, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    group_width = text_width + gap + reference_size
    text_x = max(margin, (width - group_width) // 2)
    image_x = min(width - margin - reference_size, text_x + text_width + gap)
    text_y = (header_height - text_height) // 2 - bbox[1]
    image_y = (header_height - reference_size) // 2
    draw.text((text_x, text_y), label, fill="black", font=font)

    reference = reference.copy()
    reference.thumbnail((reference_size, reference_size), Image.Resampling.LANCZOS)
    image_box = Image.new("RGB", (reference_size, reference_size), "white")
    image_box.paste(
        reference,
        (
            (reference_size - reference.width) // 2,
            (reference_size - reference.height) // 2,
        ),
    )
    header.paste(image_box, (int(image_x), int(image_y)))
    base.paste(header, (0, 0))
    return base


def _compose_demo_image(
    *,
    base: Image.Image,
    hud_state: dict[str, Any],
    hud_image: Image.Image | None,
) -> Image.Image:
    image = ImageEnhance.Brightness(base.convert("RGB")).enhance(
        DEMO_BACKGROUND_BRIGHTNESS
    )
    hud = _backend_hud_image(hud_state, hud_image)
    hud = _fit_hud_to_canvas(hud, image.size)
    image_rgba = image.convert("RGBA")
    image_rgba.alpha_composite(_green_hud_overlay(hud))
    return image_rgba.convert("RGB")


def _fit_hud_to_canvas(hud: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, "black")
    fitted = ImageOps.contain(hud, size, Image.Resampling.LANCZOS)
    canvas.paste(
        fitted,
        (
            (size[0] - fitted.width) // 2,
            (size[1] - fitted.height) // 2,
        ),
    )
    return canvas


def _backend_hud_image(
    hud_state: dict[str, Any],
    hud_image: Image.Image | None,
) -> Image.Image:
    image = Image.new("RGB", (HUD_WIDTH, HUD_HEIGHT), "black")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(_sp(20))
    step_font = _load_font(_sp(15))
    hint_font = _load_font(_sp(17))
    controls_font = _load_font(_sp(12))

    title_bbox = _draw_centered_text(
        draw,
        "Origami Guide",
        center_x=HUD_WIDTH // 2,
        y=_dp(25),
        font=title_font,
        fill=HUD_GREEN,
    )

    if hud_state.get("screen") == "start":
        hint_y = title_bbox[3] + _dp(38)
        _draw_centered_text(
            draw,
            "Double tap temple to start",
            center_x=HUD_WIDTH // 2,
            y=hint_y,
            font=hint_font,
            fill=HUD_GREEN,
        )
        _draw_centered_lines(
            draw,
            ["Double tap temple to start"],
            center_x=HUD_WIDTH // 2,
            bottom=HUD_HEIGHT - _dp(16),
            font=controls_font,
            fill=HUD_GREEN,
            line_gap=3,
        )
        return image

    draw.text(
        (_dp(18), _dp(68)),
        f"Step {hud_state.get('step_number', 1)}/{hud_state.get('step_count', 7)}",
        fill=HUD_GREEN,
        font=step_font,
    )

    if hud_image is not None:
        guide = _green_hud_asset(hud_image)
        guide.thumbnail((HUD_WIDTH - 2 * _dp(18), 180), Image.Resampling.LANCZOS)
        image.paste(
            guide,
            (
                (HUD_WIDTH - guide.width) // 2,
                _dp(94) + (180 - guide.height) // 2,
            ),
        )

    message = str(hud_state.get("message") or "")
    if message:
        message_size = _sp(21)
        fitted = _fit_font(draw, message, HUD_WIDTH - 36, message_size)
        _draw_centered_text(
            draw,
            message,
            center_x=HUD_WIDTH // 2,
            y=_dp(206),
            font=fitted,
            fill=HUD_GREEN,
        )

    auto_enabled = bool(hud_state.get("auto_check_enabled", True))
    controls = (
        ["Auto check on", "Swipe: previous/next | Double tap: reset"]
        if auto_enabled
        else ["Auto check off", "Swipe: previous/next | Double tap: reset"]
    )
    _draw_centered_lines(
        draw,
        controls,
        center_x=HUD_WIDTH // 2,
        bottom=HUD_HEIGHT - _dp(16),
        font=controls_font,
        fill=HUD_GREEN,
        line_gap=16,
    )
    return image


def _demo_placeholder(message: str) -> Image.Image:
    image = Image.new("RGB", (1024, 768), "black")
    draw = ImageDraw.Draw(image)
    font = _load_font(44)
    bbox = draw.textbbox((0, 0), message, font=font)
    draw.text(
        ((1024 - (bbox[2] - bbox[0])) // 2, (768 - (bbox[3] - bbox[1])) // 2),
        message,
        fill=HUD_DIM_GREEN,
        font=font,
    )
    return image


def _green_hud_asset(image: Image.Image) -> Image.Image:
    source = image.convert("RGBA")
    luminance = source.convert("L")
    colorized = ImageOps.colorize(luminance, black=(0, 0, 0), white=HUD_GREEN)
    colorized.putalpha(source.getchannel("A"))
    background = Image.new("RGBA", source.size, (0, 0, 0, 255))
    background.alpha_composite(colorized)
    return background.convert("RGB")


def _green_hud_overlay(image: Image.Image) -> Image.Image:
    source = image.convert("RGB")
    alpha = source.convert("L").point(lambda value: min(245, value * 3))
    glow_alpha = alpha.filter(ImageFilter.GaussianBlur(radius=2)).point(
        lambda value: min(90, value)
    )
    glow = Image.new("RGBA", source.size, (*HUD_GREEN, 0))
    glow.putalpha(glow_alpha)
    sharp = Image.new("RGBA", source.size, (*HUD_GREEN, 0))
    sharp.putalpha(alpha)
    glow.alpha_composite(sharp)
    return glow


def _dp(value: int) -> int:
    return round(value * HUD_DENSITY)


def _sp(value: int) -> int:
    return round(value * HUD_DENSITY)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    center_x: int,
    y: int,
    font: Any,
    fill: tuple[int, int, int],
) -> tuple[int, int, int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    x = center_x - width // 2 - bbox[0]
    draw.text((x, y - bbox[1]), text, fill=fill, font=font)
    rendered = draw.textbbox((x, y - bbox[1]), text, font=font)
    return (
        int(rendered[0]),
        int(rendered[1]),
        int(rendered[2]),
        int(rendered[3]),
    )


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    *,
    center_x: int,
    bottom: int,
    font: Any,
    fill: tuple[int, int, int],
    line_gap: int,
) -> None:
    metrics = [draw.textbbox((0, 0), line, font=font) for line in lines]
    heights = [bbox[3] - bbox[1] for bbox in metrics]
    total_height = sum(heights) + line_gap * max(0, len(lines) - 1)
    y = bottom - total_height
    for line, bbox, height in zip(lines, metrics, heights, strict=True):
        width = bbox[2] - bbox[0]
        x = center_x - width // 2 - bbox[0]
        draw.text((x, y - bbox[1]), line, fill=fill, font=font)
        y += height + line_gap


def _empty_hud_payload(auto_check_available: bool = True) -> dict[str, Any]:
    return {
        "type": "hud.state",
        "screen": "start",
        "phase": PHASE_WAITING,
        "step_index": 0,
        "step_number": 1,
        "step_count": 7,
        "step_id": "step_1",
        "step_title": "Step 1",
        "hud_image": "origami_step_1",
        "auto_check_enabled": auto_check_available,
        "auto_check_available": auto_check_available,
        "true_streak": 0,
        "message": "",
    }


def _frame_to_image(
    frame: VideoFrame, *, fallback_size: tuple[int, int]
) -> Image.Image:
    try:
        return frame.to_image().convert("RGB")
    except Exception:
        logger.exception("failed to convert video frame to image")
        return Image.new("RGB", fallback_size, "black")


def _save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, format="JPEG", quality=90, optimize=True)


def _find_stats(stats: Iterable[Any], stats_type: str, kind: str | None) -> Any | None:
    matches = [
        stat
        for stat in stats
        if getattr(stat, "type", None) == stats_type
        and (kind is None or getattr(stat, "kind", None) == kind)
    ]
    if not matches:
        return None
    return max(matches, key=lambda stat: _stats_int(stat, "bytesSent"))


def _stats_int(stat: Any | None, field_name: str) -> int:
    if stat is None:
        return 0
    value = getattr(stat, field_name, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _stats_float(stat: Any | None, field_name: str) -> float | None:
    if stat is None:
        return None
    value = getattr(stat, field_name, None)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return None


def _stats_text(stat: Any | None, field_name: str) -> str:
    if stat is None:
        return "n/a"
    value = getattr(stat, field_name, None)
    if value is None:
        return "n/a"
    return str(value)


def _format_kbps(value_bps: float | None) -> str:
    if value_bps is None:
        return "n/a"
    return f"{value_bps / 1000:.0f}"


def _format_ms(value_seconds: float | None) -> str:
    if value_seconds is None:
        return "n/a"
    return f"{value_seconds * 1000:.0f}"


def _format_optional_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


def _format_rtcp_loss_pct(fraction_lost: float | None) -> str:
    if fraction_lost is None:
        return "n/a"
    return f"{fraction_lost / 256 * 100:.1f}"


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
) -> Any:
    size = start_size
    while size > 10:
        font = _load_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return _load_font(size)


def _load_font(size: int) -> Any:
    for path in (
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ):
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _parse_json_object(raw_text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_overshoot_boolean(payload: dict[str, Any]) -> bool | None:
    if payload.get("ok") is False:
        return None
    raw = payload.get("result")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        with suppress(json.JSONDecodeError):
            parsed = json.loads(raw)
            if isinstance(parsed, bool):
                return parsed
            if isinstance(parsed, dict):
                return _first_boolean(parsed)
    if isinstance(raw, dict):
        return _first_boolean(raw)
    return None


def _payload_received_at(payload: dict[str, Any]) -> float:
    value = payload.get("_received_at")
    if isinstance(value, (int, float)):
        return float(value)
    return time.monotonic()


def _first_boolean(payload: dict[str, Any]) -> bool | None:
    for key in ("matches", "match", "result", "value", "ok"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    return None


def _overshoot_payload_for_log(payload: dict[str, Any]) -> dict[str, Any]:
    summarized = dict(payload)
    if "prompt" in summarized:
        summarized["prompt"] = "<active prompt>"
    return summarized


def _extract_answer_sdp(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("answer_sdp", "sdp", "answer"):
            value = payload.get(key)
            if isinstance(value, str):
                return _normalize_sdp(value)
    if isinstance(payload, str):
        return _normalize_sdp(payload)
    return ""


def _normalize_sdp(raw: str) -> str:
    trimmed = raw.strip()
    if not trimmed:
        return ""
    text = (
        trimmed.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return ""
    return "\r\n".join(lines) + "\r\n"


def _parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _response_text(response: httpx.Response) -> str:
    try:
        return response.text.strip()
    except Exception:
        return ""


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except TypeError:
        return repr(value)
