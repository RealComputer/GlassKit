from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from PIL import Image
from websockets import ConnectionClosed

from .constants import (
    BOOLEAN_OUTPUT_SCHEMA,
    DEBUG_COMPOSITE_INTERVAL_SECONDS,
    DEFAULT_OVERSHOOT_MODE,
    DEFAULT_OVERSHOOT_PROCESSING,
    OVERSHOOT_STATS_LOG_INTERVAL_SECONDS,
    OVERSHOOT_WS_AUTH_FAILURE_CLOSE_CODE,
    OVERSHOOT_WS_MAX_RECONNECT_ATTEMPTS,
    OVERSHOOT_WS_RETRY_BASE_SECONDS,
    OVERSHOOT_WS_RETRY_MAX_SECONDS,
    OVERSHOOT_WS_STREAM_ENDED_CLOSE_CODE,
    PHASE_GUIDING,
)
from .overshoot_payloads import (
    _compact_json,
    _extract_answer_sdp,
    _overshoot_payload_for_log,
    _parse_json_object,
    _parse_positive_int,
    _response_text,
)
from .origami_config import OrigamiStep
from .rendering import _compose_reference_image, _frame_to_image, _save_jpeg
from .rtc_media import (
    ReferenceCompositeTrack,
    _prefer_codec,
    _wait_for_ice_gathering_complete,
    create_overshoot_peer_connection,
)
from .session_state import OrigamiSession, SessionEvent
from .stats import (
    _find_stats,
    _format_kbps,
    _format_ms,
    _format_optional_int,
    _format_rtcp_loss_pct,
    _stats_float,
    _stats_int,
    _stats_text,
)

logger = logging.getLogger("uvicorn.error")


class OvershootRuntimeMixin:
    _auto_check_available: bool
    _debug_composite_dir: Path
    _overshoot_api_key: str
    _overshoot_api_url: str
    _overshoot_http: httpx.AsyncClient
    _overshoot_model: str
    _save_overshoot_composites: bool
    _sessions: dict[str, OrigamiSession]
    _sessions_lock: asyncio.Lock
    _steps: list[OrigamiStep]

    def current_step_for(self, session: OrigamiSession) -> OrigamiStep:
        raise NotImplementedError

    def reference_image_for(self, step: OrigamiStep) -> Image.Image:
        raise NotImplementedError

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

        pc = create_overshoot_peer_connection()

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
