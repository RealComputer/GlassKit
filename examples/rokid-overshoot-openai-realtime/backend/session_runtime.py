from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import websockets
from httpx import AsyncClient
from fastapi import HTTPException
from websockets import ConnectionClosed

from session_constants import (
    DEFAULT_OPENAI_CALLS_URL,
    DEFAULT_OPENAI_VOICE,
    DEFAULT_PROCESSING,
    GENERAL_OUTPUT_SCHEMA,
    INVENTORY_SCAN_PROMPT,
    OPENAI_SESSION_INSTRUCTIONS,
    OVERSHOOT_WS_MAX_RECONNECT_ATTEMPTS,
    OVERSHOOT_WS_RETRYABLE_CLOSE_CODES,
    OVERSHOOT_WS_RETRY_BASE_SECONDS,
    OVERSHOOT_WS_RETRY_MAX_SECONDS,
    OVERSHOOT_WS_TERMINAL_CLOSE_CODES,
    RuntimeKind,
)
from session_helpers import (
    extract_answer_sdp,
    extract_call_id,
    normalize_sdp,
    parse_positive_int,
    response_text,
)
from session_types import ControlSession, SessionEvent

logger = logging.getLogger("uvicorn.error")


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    except TypeError:
        return repr(value)


class SessionRuntimeMixin:
    if TYPE_CHECKING:
        _overshoot_api_url: str
        _overshoot_api_key: str
        _overshoot_model: str
        _openai_api_key: str
        _openai_model: str
        _overshoot_http: AsyncClient
        _openai_http: AsyncClient
        _sessions: dict[str, ControlSession]
        _sessions_lock: asyncio.Lock

        async def _require_session(self, session_id: str) -> ControlSession: ...
        async def _publish_hud_state(self, session: ControlSession) -> None: ...

    async def create_vision_session(self, session_id: str, offer_sdp: str) -> str:
        session = await self._require_session(session_id)
        await self._stop_vision_runtime(session)

        generation = session.vision_generation
        payload = {
            "source": {"type": "webrtc", "sdp": offer_sdp},
            "mode": "clip",
            "processing": DEFAULT_PROCESSING,
            "inference": {
                "prompt": INVENTORY_SCAN_PROMPT,
                "backend": "overshoot",
                "model": self._overshoot_model,
                "output_schema_json": GENERAL_OUTPUT_SCHEMA,
            },
        }

        response = await self._overshoot_http.post("/streams", json=payload)
        if not response.is_success:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to create Overshoot stream "
                    f"(HTTP {response.status_code}): {response_text(response)}"
                ),
            )

        data = response.json()
        stream_id = str(data.get("stream_id") or "").strip()
        answer_sdp = extract_answer_sdp(data.get("webrtc"))
        ttl_seconds = parse_positive_int((data.get("lease") or {}).get("ttl_seconds"))
        if not stream_id or not answer_sdp.startswith("v="):
            if stream_id:
                await self._close_overshoot_stream(stream_id)
            raise HTTPException(
                status_code=502,
                detail="Overshoot response missing a valid stream_id or answer SDP",
            )

        current = await self._get_session_if_current(session_id, generation, "vision")
        if current is None:
            await self._close_overshoot_stream(stream_id)
            logger.info(
                "session=%s dropping stale vision stream_id=%s generation=%s",
                session_id,
                stream_id,
                generation,
            )
            raise HTTPException(status_code=409, detail="session no longer active")

        current.overshoot_stream_id = stream_id
        current.overshoot_lease_ttl_seconds = ttl_seconds
        current.vision_ready = True
        current.active_prompt_text = INVENTORY_SCAN_PROMPT
        current.active_detector_key = "inventory_scan"
        current.overshoot_ws_task = asyncio.create_task(
            self._run_overshoot_ws(current.session_id, stream_id, generation),
            name=f"overshoot-ws-{current.session_id}-{generation}",
        )
        if ttl_seconds:
            current.overshoot_keepalive_task = asyncio.create_task(
                self._run_overshoot_keepalive(
                    current.session_id, stream_id, ttl_seconds, generation
                ),
                name=f"overshoot-keepalive-{current.session_id}-{generation}",
            )

        await current.queue.put(SessionEvent(kind="vision.ready"))
        logger.info(
            "session=%s vision_ready stream_id=%s generation=%s",
            current.session_id,
            stream_id,
            generation,
        )
        return answer_sdp

    async def create_realtime_session(self, session_id: str, offer_sdp: str) -> str:
        session = await self._require_session(session_id)
        await self._stop_realtime_runtime(session)

        generation = session.realtime_generation
        form = {
            "sdp": (None, offer_sdp),
            "session": (None, json.dumps(self._openai_session_config())),
        }
        upstream = await self._openai_http.post(
            DEFAULT_OPENAI_CALLS_URL,
            headers={"Authorization": f"Bearer {self._openai_api_key}"},
            files=form,
        )
        if not upstream.is_success:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to create OpenAI realtime call "
                    f"(HTTP {upstream.status_code}): {response_text(upstream)}"
                ),
            )

        call_id = extract_call_id(upstream.headers.get("location"))
        answer_sdp = normalize_sdp(upstream.text)
        if not call_id or not answer_sdp.startswith("v="):
            raise HTTPException(
                status_code=502,
                detail="OpenAI realtime response missing call_id or valid answer SDP",
            )

        current = await self._get_session_if_current(session_id, generation, "realtime")
        if current is None:
            logger.info(
                "session=%s dropping stale realtime call_id=%s generation=%s",
                session_id,
                call_id,
                generation,
            )
            raise HTTPException(status_code=409, detail="session no longer active")

        current.openai_call_id = call_id
        current.openai_sideband_task = asyncio.create_task(
            self._run_openai_sideband(current.session_id, call_id, generation),
            name=f"openai-sideband-{current.session_id}-{generation}",
        )
        logger.info(
            "session=%s realtime_answered call_id=%s generation=%s",
            current.session_id,
            call_id,
            generation,
        )
        return answer_sdp

    async def _stop_vision_runtime(self, session: ControlSession) -> None:
        session.vision_generation += 1
        session.vision_ready = False
        stream_id = session.overshoot_stream_id
        session.overshoot_stream_id = None
        session.overshoot_lease_ttl_seconds = None
        tasks: list[asyncio.Task[None]] = []
        for task in (session.overshoot_ws_task, session.overshoot_keepalive_task):
            if task is not None:
                task.cancel()
                tasks.append(task)
        session.overshoot_ws_task = None
        session.overshoot_keepalive_task = None
        if tasks:
            with suppress(Exception):
                await asyncio.gather(*tasks, return_exceptions=True)
        if stream_id:
            await self._close_overshoot_stream(stream_id)

    async def _stop_realtime_runtime(self, session: ControlSession) -> None:
        session.realtime_generation += 1
        session.realtime_ready = False
        ws = session.openai_ws
        session.openai_ws = None
        task = session.openai_sideband_task
        session.openai_sideband_task = None
        session.openai_call_id = None
        if ws is not None:
            with suppress(Exception):
                await ws.close()
        if task is not None:
            task.cancel()
            with suppress(Exception):
                await task

    async def _send_control(
        self, session: ControlSession, payload: dict[str, Any]
    ) -> None:
        with suppress(Exception):
            await session.control_ws.send_json(payload)

    async def _speak_line(self, session: ControlSession, text: str) -> None:
        if session.openai_ws is None:
            return
        line = text.strip()
        if not line:
            return
        await self._send_openai_event(session, {"type": "response.cancel"})
        session.speech_epoch += 1
        session.current_speech_text = line
        await self._publish_hud_state(session)
        await self._send_openai_user_text(session, f"Speak exactly this line: {line}")
        await self._send_openai_event(session, {"type": "response.create"})

    async def _send_openai_user_text(self, session: ControlSession, text: str) -> None:
        payload = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": text,
                    }
                ],
            },
        }
        await self._send_openai_event(session, payload)

    async def _send_openai_tool_output(
        self,
        session: ControlSession,
        *,
        call_id: str,
        output: str,
        continue_response: bool,
    ) -> None:
        if not call_id:
            return
        await self._send_openai_event(
            session,
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            },
        )
        if continue_response:
            await self._send_openai_event(session, {"type": "response.create"})

    async def _send_openai_event(
        self, session: ControlSession, payload: dict[str, Any]
    ) -> None:
        if session.openai_ws is None:
            return
        await session.openai_ws.send(json.dumps(payload))

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
                session = await self._get_session_if_current(
                    session_id, generation, "vision"
                )
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
                        response_text(response),
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
            session = await self._get_session_if_current(
                session_id, generation, "vision"
            )
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
                    attempt = 0
                    async for raw_message in overshoot_ws:
                        raw_text = (
                            raw_message.decode()
                            if isinstance(raw_message, bytes)
                            else raw_message
                        )
                        try:
                            payload = json.loads(raw_text)
                        except json.JSONDecodeError:
                            logger.info(
                                "session=%s overshoot bad json=%s", session_id, raw_text
                            )
                            continue
                        logger.info(
                            "session=%s overshoot payload=%s",
                            session_id,
                            _compact_json(payload),
                        )

                        current = await self._get_session_if_current(
                            session_id, generation, "vision"
                        )
                        if current is None:
                            return
                        await current.queue.put(
                            SessionEvent(
                                kind="overshoot.result",
                                payload={
                                    "generation": generation,
                                    **payload,
                                },
                            )
                        )
            except asyncio.CancelledError:
                raise
            except ConnectionClosed as exc:
                if exc.code in OVERSHOOT_WS_TERMINAL_CLOSE_CODES:
                    session = await self._get_session_if_current(
                        session_id, generation, "vision"
                    )
                    if session is not None:
                        await session.queue.put(
                            SessionEvent(
                                kind="overshoot.closed",
                                payload={
                                    "generation": generation,
                                    "reason": exc.reason,
                                },
                            )
                        )
                    return
                if exc.code not in OVERSHOOT_WS_RETRYABLE_CLOSE_CODES:
                    session = await self._get_session_if_current(
                        session_id, generation, "vision"
                    )
                    if session is not None:
                        await session.queue.put(
                            SessionEvent(
                                kind="overshoot.closed",
                                payload={
                                    "generation": generation,
                                    "reason": exc.reason,
                                },
                            )
                        )
                    return
            except Exception:
                logger.exception("session=%s overshoot websocket crashed", session_id)

            attempt += 1
            if attempt > OVERSHOOT_WS_MAX_RECONNECT_ATTEMPTS:
                session = await self._get_session_if_current(
                    session_id, generation, "vision"
                )
                if session is not None:
                    await session.queue.put(
                        SessionEvent(
                            kind="overshoot.closed",
                            payload={
                                "generation": generation,
                                "reason": "reconnect_exhausted",
                            },
                        )
                    )
                return
            delay = min(
                OVERSHOOT_WS_RETRY_MAX_SECONDS,
                OVERSHOOT_WS_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
            )
            await asyncio.sleep(delay)

    async def _run_openai_sideband(
        self,
        session_id: str,
        call_id: str,
        generation: int,
    ) -> None:
        url = f"wss://api.openai.com/v1/realtime?call_id={call_id}"
        try:
            async with websockets.connect(
                url,
                additional_headers={"Authorization": f"Bearer {self._openai_api_key}"},
            ) as ws:
                session = await self._get_session_if_current(
                    session_id, generation, "realtime"
                )
                if session is None:
                    return
                session.openai_ws = ws
                session.realtime_ready = True
                await session.queue.put(SessionEvent(kind="realtime.ready"))

                async for raw in ws:
                    raw_text = raw.decode() if isinstance(raw, bytes) else raw
                    try:
                        payload = json.loads(raw_text)
                    except json.JSONDecodeError:
                        logger.info(
                            "session=%s openai bad json=%s", session_id, raw_text
                        )
                        continue

                    current = await self._get_session_if_current(
                        session_id, generation, "realtime"
                    )
                    if current is None:
                        return

                    message_type = payload.get("type")
                    if message_type == "response.done":
                        await current.queue.put(
                            SessionEvent(
                                kind="openai.response.done",
                                payload={
                                    "generation": generation,
                                    "response": payload.get("response") or {},
                                },
                            )
                        )
                    elif message_type == "error":
                        await current.queue.put(
                            SessionEvent(
                                kind="openai.error",
                                payload={
                                    "generation": generation,
                                    "message": payload.get("error"),
                                },
                            )
                        )
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as exc:
            logger.info(
                "session=%s openai sideband closed code=%s reason=%s",
                session_id,
                exc.code,
                exc.reason,
            )
        except Exception:
            logger.exception("session=%s openai sideband failed", session_id)
        finally:
            session = await self._get_session_if_current(
                session_id, generation, "realtime"
            )
            if session is not None:
                if session.openai_ws is not None:
                    with suppress(Exception):
                        await session.openai_ws.close()
                session.openai_ws = None
                session.realtime_ready = False
                await session.queue.put(
                    SessionEvent(
                        kind="realtime.closed",
                        payload={"generation": generation},
                    )
                )

    async def _get_session_if_current(
        self,
        session_id: str,
        generation: int,
        runtime: RuntimeKind,
    ) -> ControlSession | None:
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None or session.destroyed:
            return None
        current_generation = (
            session.vision_generation
            if runtime == "vision"
            else session.realtime_generation
        )
        if generation != current_generation:
            return None
        return session

    async def _close_overshoot_stream(self, stream_id: str) -> None:
        response = await self._overshoot_http.delete(f"/streams/{stream_id}")
        if not response.is_success and response.status_code != 404:
            logger.warning(
                "stream=%s close failed status=%s body=%s",
                stream_id,
                response.status_code,
                response_text(response),
            )

    def _openai_session_config(self) -> dict[str, Any]:
        return {
            "type": "realtime",
            "model": self._openai_model,
            "audio": {
                "output": {
                    "voice": DEFAULT_OPENAI_VOICE,
                }
            },
            "instructions": OPENAI_SESSION_INSTRUCTIONS,
            "tools": [
                {
                    "type": "function",
                    "name": "list_recipes",
                    "description": "List available recipe filename ids.",
                },
                {
                    "type": "function",
                    "name": "activate_recipe",
                    "description": (
                        "Activate the chosen recipe id from the filenames returned by "
                        "list_recipes."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "The recipe filename id to activate.",
                            }
                        },
                        "required": ["id"],
                    },
                },
            ],
        }
