from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from session_manager import (
    DEFAULT_MODEL,
    DEFAULT_OVERSHOOT_API_URL,
    DEFAULT_PROMPT,
    OvershootSessionManager,
    env_or_default,
    load_processing_config,
)

logger = logging.getLogger("uvicorn.error")


class VisionSessionCreateRequest(BaseModel):
    offer_sdp: str


class VisionSessionCreateResponse(BaseModel):
    session_id: str
    answer_sdp: str


class StatusResponse(BaseModel):
    status: str


session_manager: OvershootSessionManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global session_manager

    api_key = os.getenv("OVERSHOOT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set OVERSHOOT_API_KEY in backend/.env")

    api_url = env_or_default("OVERSHOOT_API_URL", DEFAULT_OVERSHOOT_API_URL)
    prompt = env_or_default("OVERSHOOT_PROMPT", DEFAULT_PROMPT)
    model = env_or_default("OVERSHOOT_MODEL", DEFAULT_MODEL)
    processing = load_processing_config()

    session_manager = OvershootSessionManager(
        api_url=api_url,
        api_key=api_key,
        prompt=prompt,
        model=model,
        processing=processing,
    )

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

    session_id, answer_sdp = await manager.create_session(offer_sdp)
    return VisionSessionCreateResponse(session_id=session_id, answer_sdp=answer_sdp)


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
