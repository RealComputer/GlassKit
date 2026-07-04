from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiortc import MediaStreamTrack, RTCSessionDescription
from aiortc.rtcdatachannel import RTCDataChannel
from av import VideoFrame
from fastapi import HTTPException
from PIL import Image

from .constants import (
    FOLD_CHECK_STEP_RESULT_GRACE_SECONDS,
    PHASE_COMPLETED,
    PHASE_ERROR,
    PHASE_GUIDING,
    PHASE_STEP_DONE,
    PHASE_WAITING,
)
from .fold_check import load_fold_check_steps, parse_fold_check_result
from .origami_config import OrigamiStep
from .payload_utils import (
    _compact_json,
    _parse_json_object,
    _payload_received_at,
)
from .fold_check_runtime import FoldCheckRuntime
from .rendering import (
    _compose_demo_image,
    _demo_placeholder,
    _empty_hud_payload,
    _frame_to_image,
)
from .rtc_media import (
    DemoCompositeTrack,
    _prefer_codec,
    _wait_for_ice_gathering_complete,
    create_peer_connection,
)
from .session_state import DemoViewer, OrigamiSession, SessionEvent

logger = logging.getLogger("uvicorn.error")

__all__ = [
    "OrigamiSessionManager",
]


class OrigamiSessionManager:
    def __init__(
        self,
        *,
        fold_check_api_key: str,
        fold_check_model: str,
        steps_path: Path,
        auto_check_available: bool = True,
        save_fold_check_composites: bool = False,
        debug_composite_dir: Path | None = None,
        record_fold_check_inputs: bool = True,
        fold_check_input_recording_dir: Path | None = None,
    ) -> None:
        self._auto_check_available = auto_check_available
        debug_composite_dir = (
            debug_composite_dir
            if debug_composite_dir is not None
            else steps_path.parent.parent / "debug" / "fold-check-composites"
        )
        fold_check_input_recording_dir = (
            fold_check_input_recording_dir
            if fold_check_input_recording_dir is not None
            else steps_path.parent.parent / "debug" / "fold-check-inputs"
        )
        self._steps = load_fold_check_steps(steps_path)
        self._reference_images = self._load_reference_images(self._steps)
        self._hud_images = self._load_hud_images(self._steps, steps_path.parent)
        self._sessions: dict[str, OrigamiSession] = {}
        self._viewers: dict[str, DemoViewer] = {}
        self._sessions_lock = asyncio.Lock()
        self._viewers_lock = asyncio.Lock()
        self._fold_check = FoldCheckRuntime(
            auto_check_available=auto_check_available,
            api_key=fold_check_api_key,
            model=fold_check_model,
            sessions=self._sessions,
            sessions_lock=self._sessions_lock,
            current_step_for=self.current_step_for,
            reference_image_for=self.reference_image_for,
            save_composites=save_fold_check_composites,
            debug_composite_dir=debug_composite_dir,
            record_inputs=record_fold_check_inputs,
            input_recording_dir=fold_check_input_recording_dir,
        )

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

        await self._fold_check.close()

    async def create_media_session(self, offer_sdp: str) -> dict[str, str]:
        offer_sdp = offer_sdp.strip()
        if not offer_sdp:
            raise HTTPException(status_code=422, detail="offer_sdp must not be empty")

        session_id = str(uuid.uuid4())
        session = OrigamiSession(session_id=session_id)
        pc = create_peer_connection()
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
        pc = create_peer_connection()
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
            await self._fold_check.maybe_save_debug_composite(session)
            if session.phase == PHASE_GUIDING and session.auto_check_enabled:
                await self._fold_check.sync_for_current_step(session)
            return
        if event.kind == "fold_check.result":
            await self._handle_fold_check_result(session, event.payload)
            return
        if event.kind == "fold_check.closed":
            await self._handle_fold_check_closed(session, event.payload)
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
        await self._fold_check.sync_for_current_step(session)

    async def _reset_to_waiting(self, session: OrigamiSession) -> None:
        await self._cancel_done_task(session)
        await self._fold_check.stop(session)
        session.phase = PHASE_WAITING
        session.step_index = 0
        session.true_streak = 0
        session.auto_check_enabled = self._auto_check_available
        session.fold_check.clear_prompt_tracking()
        session.guiding_step_started_at = 0.0
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
                await self._fold_check.stop(session)
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
        await self._fold_check.sync_for_current_step(session)

    async def _toggle_auto_check(self, session: OrigamiSession) -> None:
        if session.phase not in {PHASE_GUIDING, PHASE_STEP_DONE}:
            return
        if not self._auto_check_available:
            session.auto_check_enabled = False
            await self._fold_check.stop(session)
            await self._publish_hud_state(session)
            return
        session.auto_check_enabled = not session.auto_check_enabled
        session.true_streak = 0
        if session.auto_check_enabled and session.phase == PHASE_GUIDING:
            await self._fold_check.sync_for_current_step(session)
        else:
            await self._fold_check.stop(session)
        await self._publish_hud_state(session)

    async def _handle_fold_check_result(
        self,
        session: OrigamiSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.fold_check.generation:
            return
        if payload.get("step_index") != session.step_index:
            return
        if session.phase != PHASE_GUIDING or not session.auto_check_enabled:
            return

        received_at = _payload_received_at(payload)
        if received_at < session.guiding_step_started_at:
            logger.info(
                "session=%s ignoring fold-check result received before current step",
                session.session_id,
            )
            return
        if received_at < session.fold_check.ignore_results_until:
            logger.info(
                "session=%s ignoring fold-check result during step settle window",
                session.session_id,
            )
            return

        prompt = str(payload.get("prompt") or "")
        if (
            prompt
            and session.fold_check.active_prompt
            and not prompt.startswith(session.fold_check.active_prompt)
        ):
            logger.info(
                "session=%s ignoring result for stale prompt",
                session.session_id,
            )
            return

        observed = parse_fold_check_result(payload)
        if observed is None:
            logger.info(
                "session=%s ignoring non-boolean fold-check payload=%s",
                session.session_id,
                _compact_json(payload),
            )
            return

        if observed:
            session.true_streak += 1
        else:
            session.true_streak = 0

        logger.info(
            "session=%s step=%s fold-check observed=%s streak=%s",
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
            await self._fold_check.stop(session)
            await self._publish_hud_state(session)
            return

        session.step_index += 1
        session.phase = PHASE_GUIDING
        session.true_streak = 0
        self._mark_guiding_step_started(session)
        await self._publish_hud_state(session)
        await self._fold_check.sync_for_current_step(session)

    async def _handle_fold_check_closed(
        self,
        session: OrigamiSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.fold_check.generation:
            return
        if session.phase in {PHASE_WAITING, PHASE_COMPLETED, PHASE_ERROR}:
            return
        if not self._auto_check_available:
            return
        if not session.auto_check_enabled:
            return
        await self._fail_session(
            session, "Fold check stream ended. Double tap to restart."
        )

    async def _fail_session(self, session: OrigamiSession, message: str) -> None:
        await self._cancel_done_task(session)
        await self._fold_check.stop(session)
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
        session.fold_check.mark_guiding_step_started(
            now,
            FOLD_CHECK_STEP_RESULT_GRACE_SECONDS,
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
        await self._fold_check.stop(session)
        for task in session.track_tasks:
            task.cancel()
        if session.track_tasks:
            await asyncio.gather(*session.track_tasks, return_exceptions=True)
        await session.camera_frames.close()
        if session.media_pc is not None:
            await session.media_pc.close()
            session.media_pc = None

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
