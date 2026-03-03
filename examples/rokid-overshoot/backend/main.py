from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger("uvicorn.error")

DEFAULT_OVERSHOOT_API_URL = "https://api.overshoot.ai/v0.2"
DEFAULT_PROMPT = "Describe what you see"
DEFAULT_MODEL = "Qwen/Qwen3-VL-30B-A3B-Instruct"
DEFAULT_PROCESSING = {
    "target_fps": 6,
    "clip_length_seconds": 0.5,
    "delay_seconds": 0.5,
}


class VisionSessionCreateRequest(BaseModel):
    offer_sdp: str


class VisionSessionCreateResponse(BaseModel):
    session_id: str
    answer_sdp: str


class StatusResponse(BaseModel):
    status: str


@dataclass
class VisionSession:
    session_id: str
    stream_id: str
    lease_ttl_seconds: int | None
    android_ws: WebSocket | None = None
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)
    overshoot_ws_task: asyncio.Task[None] | None = None
    keepalive_task: asyncio.Task[None] | None = None


class OvershootSessionManager:
    def __init__(self, api_url: str, api_key: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._http = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=httpx.Timeout(20.0),
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        self._sessions: dict[str, VisionSession] = {}
        self._sessions_lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._sessions_lock:
            session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            await self.close_session(session_id, reason="server shutdown")
        await self._http.aclose()

    async def create_session(self, offer_sdp: str) -> VisionSessionCreateResponse:
        payload = {
            "source": {"type": "webrtc", "sdp": offer_sdp},
            "mode": "clip",
            "processing": DEFAULT_PROCESSING,
            "inference": {
                "prompt": DEFAULT_PROMPT,
                "backend": "overshoot",
                "model": DEFAULT_MODEL,
            },
        }

        response = await self._http.post("/streams", json=payload)
        if not response.is_success:
            detail = _response_text(response)
            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to create Overshoot stream "
                    f"(HTTP {response.status_code}): {detail}"
                ),
            )

        data = response.json()
        stream_id = str(data.get("stream_id") or "").strip()
        answer_sdp = _extract_answer_sdp(data.get("webrtc"))
        ttl_seconds = _parse_positive_int((data.get("lease") or {}).get("ttl_seconds"))

        if not stream_id or not answer_sdp:
            if stream_id:
                await self._close_overshoot_stream(stream_id)
            raise HTTPException(
                status_code=502,
                detail="Overshoot response missing stream_id or WebRTC answer SDP",
            )

        if not answer_sdp.startswith("v="):
            if stream_id:
                await self._close_overshoot_stream(stream_id)
            raise HTTPException(
                status_code=502,
                detail=(
                    "Overshoot answer SDP has unexpected format: "
                    f"{_sdp_diagnostics(answer_sdp)}"
                ),
            )

        session_id = str(uuid.uuid4())
        session = VisionSession(
            session_id=session_id,
            stream_id=stream_id,
            lease_ttl_seconds=ttl_seconds,
        )

        async with self._sessions_lock:
            self._sessions[session_id] = session

        session.overshoot_ws_task = asyncio.create_task(
            self._run_overshoot_ws(session),
            name=f"overshoot-ws-{session_id}",
        )
        if ttl_seconds:
            session.keepalive_task = asyncio.create_task(
                self._run_keepalive(session),
                name=f"overshoot-keepalive-{session_id}",
            )

        logger.info(
            "session=%s created stream_id=%s ttl=%s",
            session_id,
            stream_id,
            ttl_seconds,
        )
        return VisionSessionCreateResponse(session_id=session_id, answer_sdp=answer_sdp)

    async def attach_android_ws(self, session_id: str, websocket: WebSocket) -> bool:
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None:
            return False

        existing_ws = session.android_ws
        if existing_ws is not None:
            with suppress(Exception):
                await existing_ws.close(code=1000, reason="superseded by new client")
        session.android_ws = websocket
        return True

    async def close_session(self, session_id: str, reason: str) -> None:
        current_task = asyncio.current_task()

        async with self._sessions_lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return

        session.shutdown_event.set()

        tasks_to_cancel: list[asyncio.Task[None]] = []
        for task in (session.overshoot_ws_task, session.keepalive_task):
            if task is None or task is current_task:
                continue
            if not task.done():
                task.cancel()
            tasks_to_cancel.append(task)

        ws = session.android_ws
        if ws is not None:
            with suppress(Exception):
                await ws.close(code=1000, reason=reason[:120])

        if tasks_to_cancel:
            with suppress(Exception):
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

        await self._close_overshoot_stream(session.stream_id)
        logger.info("session=%s closed reason=%s", session_id, reason)

    async def _run_keepalive(self, session: VisionSession) -> None:
        ttl_seconds = session.lease_ttl_seconds
        if ttl_seconds is None:
            return

        interval_seconds = max(ttl_seconds / 2.0, 5.0)
        logger.info(
            "session=%s keepalive started interval=%.1fs",
            session.session_id,
            interval_seconds,
        )

        try:
            while not session.shutdown_event.is_set():
                try:
                    await asyncio.wait_for(
                        session.shutdown_event.wait(),
                        timeout=interval_seconds,
                    )
                    return
                except TimeoutError:
                    pass

                response = await self._http.post(
                    f"/streams/{session.stream_id}/keepalive"
                )
                if not response.is_success:
                    logger.error(
                        "session=%s keepalive failed status=%s body=%s",
                        session.session_id,
                        response.status_code,
                        _response_text(response),
                    )
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s keepalive task crashed", session.session_id)

        if not session.shutdown_event.is_set():
            await self.close_session(session.session_id, reason="keepalive failed")

    async def _run_overshoot_ws(self, session: VisionSession) -> None:
        ws_base = self._api_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        ws_url = f"{ws_base}/ws/streams/{session.stream_id}"

        logger.info("session=%s connecting overshoot ws=%s", session.session_id, ws_url)

        try:
            async with websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as overshoot_ws:
                await overshoot_ws.send(json.dumps({"api_key": self._api_key}))
                async for message in overshoot_ws:
                    if session.shutdown_event.is_set():
                        return
                    if isinstance(message, str):
                        await self._handle_overshoot_message(session, message)
                    else:
                        logger.info(
                            "session=%s ignoring binary overshoot message bytes=%s",
                            session.session_id,
                            len(message),
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "session=%s overshoot websocket failed", session.session_id
            )

        if not session.shutdown_event.is_set():
            await self.close_session(
                session.session_id, reason="overshoot websocket closed"
            )

    async def _handle_overshoot_message(
        self, session: VisionSession, raw_text: str
    ) -> None:
        logger.info(
            "session=%s stream=%s overshoot_message=%s",
            session.session_id,
            session.stream_id,
            raw_text,
        )

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning("session=%s invalid JSON from Overshoot", session.session_id)
            return
        if not isinstance(payload, dict):
            return

        result_text = str(payload.get("result") or "").strip()
        if not result_text:
            return

        await self._send_result_to_android(session, result_text)

    async def _send_result_to_android(self, session: VisionSession, text: str) -> None:
        websocket = session.android_ws
        if websocket is None:
            return

        try:
            await websocket.send_json({"type": "result", "text": text})
        except Exception:
            logger.exception(
                "session=%s failed to send result to Android", session.session_id
            )
            await self.close_session(
                session.session_id,
                reason="android websocket send failed",
            )

    async def _close_overshoot_stream(self, stream_id: str) -> None:
        if not stream_id:
            return
        try:
            response = await self._http.delete(f"/streams/{stream_id}")
            if not response.is_success:
                logger.warning(
                    "failed to close stream_id=%s status=%s body=%s",
                    stream_id,
                    response.status_code,
                    _response_text(response),
                )
        except Exception:
            logger.exception("failed to close stream_id=%s", stream_id)


def _parse_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        ivalue = int(value)
        return ivalue if ivalue > 0 else None
    return None


def _extract_answer_sdp(webrtc_payload: Any) -> str:
    if isinstance(webrtc_payload, dict):
        return _normalize_sdp(webrtc_payload.get("sdp"))
    if isinstance(webrtc_payload, str):
        raw = webrtc_payload.strip()
        parsed = _parse_json(raw)
        if isinstance(parsed, dict):
            return _normalize_sdp(parsed.get("sdp"))
        return _normalize_sdp(raw)
    return ""


def _parse_json(raw: str) -> Any | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _normalize_sdp(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    text = value.strip()
    if not text:
        return ""

    # Convert escaped newlines if the payload is still escaped.
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    # Normalize all newline variants and then restore canonical SDP CRLF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return ""
    return "\r\n".join(lines) + "\r\n"


def _sdp_diagnostics(sdp: str) -> str:
    normalized = sdp.replace("\r\n", "\n")
    line_count = len([line for line in normalized.split("\n") if line])
    preview = normalized[:80].replace("\n", "\\n")
    return f"len={len(sdp)} lines={line_count} preview='{preview}'"


def _response_text(response: httpx.Response) -> str:
    try:
        return response.text.strip()
    except Exception:
        return "<unreadable response body>"


session_manager: OvershootSessionManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global session_manager

    api_key = os.getenv("OVERSHOOT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set OVERSHOOT_API_KEY in backend/.env")

    api_url = os.getenv("OVERSHOOT_API_URL", DEFAULT_OVERSHOOT_API_URL).strip()
    session_manager = OvershootSessionManager(api_url=api_url, api_key=api_key)

    try:
        yield
    finally:
        manager = session_manager
        session_manager = None
        if manager is not None:
            await manager.close()


app = FastAPI(lifespan=lifespan)


@app.post("/vision/session", response_model=VisionSessionCreateResponse)
async def create_vision_session(
    payload: VisionSessionCreateRequest,
) -> VisionSessionCreateResponse:
    manager = _require_manager()

    offer_sdp = payload.offer_sdp.strip()
    if not offer_sdp:
        raise HTTPException(status_code=422, detail="offer_sdp must not be empty")

    return await manager.create_session(offer_sdp)


@app.websocket("/vision/session/{session_id}/events")
async def vision_session_events(websocket: WebSocket, session_id: str) -> None:
    manager = _require_manager()

    await websocket.accept()
    attached = await manager.attach_android_ws(session_id, websocket)
    if not attached:
        await websocket.send_json({"type": "error", "message": "session not found"})
        await websocket.close(code=1008, reason="session not found")
        return

    logger.info("session=%s android websocket connected", session_id)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.close_session(session_id, reason="android websocket disconnected")


@app.delete("/vision/session/{session_id}", response_model=StatusResponse)
async def stop_vision_session(session_id: str) -> StatusResponse:
    manager = _require_manager()
    await manager.close_session(session_id, reason="client requested stop")
    return StatusResponse(status="ok")


def _require_manager() -> OvershootSessionManager:
    if session_manager is None:
        raise RuntimeError("Session manager is not initialized")
    return session_manager
