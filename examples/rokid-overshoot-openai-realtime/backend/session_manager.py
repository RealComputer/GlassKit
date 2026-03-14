from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, WebSocket

from recipe_catalog import RecipeCatalog
from session_constants import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OVERSHOOT_API_URL,
    DEFAULT_OVERSHOOT_MODEL,
)
from session_runtime import SessionRuntimeMixin
from session_types import ControlSession, SessionEvent
from session_workflow import SessionWorkflowMixin

__all__ = [
    "DEFAULT_OPENAI_MODEL",
    "DEFAULT_OVERSHOOT_API_URL",
    "DEFAULT_OVERSHOOT_MODEL",
    "MocktailSessionManager",
]


class MocktailSessionManager(SessionWorkflowMixin, SessionRuntimeMixin):
    def __init__(
        self,
        *,
        overshoot_api_url: str,
        overshoot_api_key: str,
        overshoot_model: str,
        openai_api_key: str,
        openai_model: str,
        recipe_dir: Path,
    ) -> None:
        self._overshoot_api_url = overshoot_api_url.rstrip("/")
        self._overshoot_api_key = overshoot_api_key
        self._overshoot_model = overshoot_model
        self._openai_api_key = openai_api_key
        self._openai_model = openai_model
        self._recipes = RecipeCatalog(recipe_dir)
        self._overshoot_http = httpx.AsyncClient(
            base_url=self._overshoot_api_url,
            timeout=httpx.Timeout(20.0),
            headers={"Authorization": f"Bearer {self._overshoot_api_key}"},
        )
        self._openai_http = httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        self._sessions: dict[str, ControlSession] = {}
        self._sessions_lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._sessions_lock:
            session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            await self.destroy_session(session_id, reason="server shutdown")
        await self._overshoot_http.aclose()
        await self._openai_http.aclose()

    async def create_control_session(self, websocket: WebSocket) -> str:
        session_id = str(uuid.uuid4())
        session = ControlSession(session_id=session_id, control_ws=websocket)
        session.loop_task = asyncio.create_task(
            self._run_session_loop(session),
            name=f"session-loop-{session_id}",
        )
        async with self._sessions_lock:
            self._sessions[session_id] = session

        await self._send_control(
            session,
            {
                "type": "session.ready",
                "session_id": session_id,
            },
        )
        await self._publish_hud_state(session)
        return session_id

    async def handle_control_message(
        self, session_id: str, payload: dict[str, Any]
    ) -> None:
        session = await self._require_session(session_id)
        message_type = str(payload.get("type") or "").strip()
        if not message_type:
            return
        await session.queue.put(SessionEvent(kind=message_type, payload=payload))

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

    async def _require_session(self, session_id: str) -> ControlSession:
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session
