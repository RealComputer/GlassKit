from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from session_manager import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OVERSHOOT_API_URL,
    DEFAULT_OVERSHOOT_MODEL,
    MocktailSessionManager,
)


class VisionSessionCreateRequest(BaseModel):
    offer_sdp: str


manager: MocktailSessionManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global manager

    overshoot_api_key = os.getenv("OVERSHOOT_API_KEY", "").strip()
    if not overshoot_api_key:
        raise RuntimeError("Set OVERSHOOT_API_KEY in backend/.env")

    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_api_key:
        raise RuntimeError("Set OPENAI_API_KEY in backend/.env")

    overshoot_api_url = os.getenv(
        "OVERSHOOT_API_URL", DEFAULT_OVERSHOOT_API_URL
    ).strip()
    overshoot_model = os.getenv("OVERSHOOT_MODEL", DEFAULT_OVERSHOOT_MODEL).strip()
    openai_model = os.getenv("OPENAI_REALTIME_MODEL", DEFAULT_OPENAI_MODEL).strip()
    recipe_dir = Path(__file__).with_name("recipes")

    manager = MocktailSessionManager(
        overshoot_api_url=overshoot_api_url,
        overshoot_api_key=overshoot_api_key,
        overshoot_model=overshoot_model,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        recipe_dir=recipe_dir,
    )
    try:
        yield
    finally:
        current = manager
        manager = None
        if current is not None:
            await current.close()


app = FastAPI(lifespan=lifespan)


@app.websocket("/session/control")
async def session_control(websocket: WebSocket) -> None:
    current = require_manager()
    await websocket.accept()
    session_id = await current.create_control_session(websocket)

    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                await websocket.send_json(
                    {
                        "type": "hud.error",
                        "message": "Control message must be a JSON object.",
                    }
                )
                continue
            await current.handle_control_message(session_id, payload)
    except WebSocketDisconnect:
        pass
    finally:
        await current.destroy_session(
            session_id, reason="control websocket disconnected"
        )


@app.post("/session/{session_id}/vision")
async def create_vision_session(
    session_id: str,
    payload: VisionSessionCreateRequest,
) -> dict[str, str]:
    current = require_manager()
    offer_sdp = payload.offer_sdp.strip()
    if not offer_sdp:
        raise HTTPException(status_code=422, detail="offer_sdp must not be empty")

    answer_sdp = await current.create_vision_session(session_id, offer_sdp)
    return {"answer_sdp": answer_sdp}


@app.post("/session/{session_id}/realtime")
async def create_realtime_session(session_id: str, request: Request) -> Response:
    current = require_manager()
    offer_sdp = (await request.body()).decode().strip()
    if not offer_sdp:
        raise HTTPException(status_code=422, detail="offer SDP must not be empty")

    answer_sdp = await current.create_realtime_session(session_id, offer_sdp)
    return Response(content=answer_sdp, media_type="application/sdp")


def require_manager() -> MocktailSessionManager:
    if manager is None:
        raise RuntimeError("Session manager is not initialized")
    return manager
