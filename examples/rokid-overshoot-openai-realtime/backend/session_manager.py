from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
import websockets
from fastapi import HTTPException, WebSocket
from pydantic import BaseModel, Field, ValidationError
from websockets import ConnectionClosed
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger("uvicorn.error")

DEFAULT_OVERSHOOT_API_URL = "https://api.overshoot.ai/v0.2"
DEFAULT_OPENAI_CALLS_URL = "https://api.openai.com/v1/realtime/calls"
DEFAULT_OVERSHOOT_MODEL = "Qwen/Qwen3.5-27B"
DEFAULT_OPENAI_MODEL = "gpt-realtime-1.5"
DEFAULT_OPENAI_VOICE = "marin"
DEFAULT_PROCESSING = {
    "target_fps": 6,
    "clip_length_seconds": 0.5,
    "delay_seconds": 0.5,
}
INVENTORY_SCAN_PROMPT = (
    "Look at the current scene and return JSON with an `ingredients` array containing "
    "up to 3 clearly visible drink bottle or garnish names. Use short lowercase names "
    'like "orange juice", "blue gatorade", or "lime". Include only visible items. '
    "Do not infer hidden items. Do not add any explanation."
)
GENERAL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ingredients": {
            "anyOf": [
                {"type": "array", "items": {"type": "string"}},
                {"type": "null"},
            ]
        },
        "color": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ]
        },
        "state": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ]
        },
        "flag": {
            "anyOf": [
                {"type": "boolean"},
                {"type": "null"},
            ]
        },
        "level": {
            "anyOf": [
                {"type": "integer", "minimum": 0, "maximum": 10},
                {"type": "string"},
                {"type": "null"},
            ]
        },
    },
    "additionalProperties": False,
}
OPENAI_SESSION_INSTRUCTIONS = """
# Role
- You only help with two things in this app:
  1. choosing a recipe from filenames after the server sends detected ingredients
  2. speaking exact lines that the server provides later

# Recipe selection
- When the server asks you to choose a recipe, first call `list_recipes`, then call `activate_recipe`.
- Choose exactly one recipe id from the filenames returned by `list_recipes`.
- Use the detected ingredient names and filename keywords only.
- Do not speak during recipe selection.

# Spoken guidance
- When the server message starts with `Speak exactly this line:`, speak that line exactly.
- Do not paraphrase, summarize, add commentary, or call tools in that case.
- Do not invent workflow decisions. The server decides the workflow.
""".strip()

OVERSHOOT_WS_MAX_RECONNECT_ATTEMPTS = 8
OVERSHOOT_WS_RETRY_BASE_SECONDS = 1.0
OVERSHOOT_WS_RETRY_MAX_SECONDS = 15.0
OVERSHOOT_WS_RETRYABLE_CLOSE_CODES = {1012, 1013}
OVERSHOOT_WS_TERMINAL_CLOSE_CODES = {1001, 1008}

TURN_END_EVENTS = {
    "input_audio_buffer.committed",
}

PHASE_WAITING = "WAITING_FOR_START"
PHASE_CONNECTING = "CONNECTING"
PHASE_INVENTORY = "INVENTORY_SCAN"
PHASE_RECIPE_SELECTION = "RECIPE_SELECTION"
PHASE_GUIDING = "GUIDING"
PHASE_COMPLETED = "COMPLETED"
PHASE_ERROR = "ERROR"

EvaluationMode = Literal[
    "match_value",
    "numeric_threshold_with_progress_once",
    "count_rising_edges_true",
    "enum_progress_once_then_complete",
    "momentary_true_complete",
]


class RecipeTask(BaseModel):
    id: str
    text: str


class RecipeDetector(BaseModel):
    prompt: str
    field: Literal["ingredients", "color", "state", "flag", "level"]


class RecipeCondition(BaseModel):
    eq: int | float | str | bool | None = None
    gt: int | float | None = None
    gte: int | float | None = None
    lt: int | float | None = None
    lte: int | float | None = None


class RecipeMilestone(BaseModel):
    count: int
    speech: str | None = None
    next_step_id: str | None = None


class RecipeStep(BaseModel):
    id: str
    task_id: str
    evaluation_mode: EvaluationMode
    detector_key: str
    expected_value: str | int | float | bool | None = None
    ignored_values: list[Any] = Field(default_factory=list)
    ignore_values: list[Any] = Field(default_factory=list)
    value_path: str | None = None
    progress_condition: RecipeCondition | None = None
    progress_once_speech: str | None = None
    complete_condition: RecipeCondition | None = None
    complete_speech: str | None = None
    next_step_id: str | None = None
    target_count: int | None = None
    milestones: list[RecipeMilestone] = Field(default_factory=list)
    count_edge: str | None = None
    rearm_condition: str | None = None
    speak_on_observation_change_only: bool = False
    on_enter_speech: str | None = None
    mismatch_speech: str | None = None
    success_speech: str | None = None
    progress_value: str | None = None
    complete_value: str | None = None
    complete_on: bool | None = None

    def ignored_values_list(self) -> list[Any]:
        return [*self.ignored_values, *self.ignore_values]


class Recipe(BaseModel):
    id: str
    display_name: str
    start_step_id: str
    tasks: list[RecipeTask]
    detectors: dict[str, RecipeDetector]
    steps: list[RecipeStep]


@dataclass
class StepRuntimeState:
    last_observed_value: Any = None
    last_spoken_observation: Any = None
    progress_flags: set[str] = field(default_factory=set)
    counter: int = 0
    previous_boolean_value: bool = False


@dataclass
class SessionEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ControlSession:
    session_id: str
    control_ws: WebSocket
    queue: asyncio.Queue[SessionEvent] = field(default_factory=asyncio.Queue)
    loop_task: asyncio.Task[None] | None = None
    phase: str = PHASE_WAITING
    speech_epoch: int = 0
    destroyed: bool = False
    vision_generation: int = 0
    realtime_generation: int = 0
    vision_ready: bool = False
    realtime_ready: bool = False
    overshoot_stream_id: str | None = None
    overshoot_lease_ttl_seconds: int | None = None
    overshoot_ws_task: asyncio.Task[None] | None = None
    overshoot_keepalive_task: asyncio.Task[None] | None = None
    openai_call_id: str | None = None
    openai_ws: ClientConnection | None = None
    openai_sideband_task: asyncio.Task[None] | None = None
    active_prompt_text: str | None = None
    active_detector_key: str | None = None
    inventory_signature: tuple[str, ...] | None = None
    inventory_hits: int = 0
    inventory_items: list[str] = field(default_factory=list)
    recipe: Recipe | None = None
    step_lookup: dict[str, RecipeStep] = field(default_factory=dict)
    step_index_by_id: dict[str, int] = field(default_factory=dict)
    current_step_id: str | None = None
    step_state: StepRuntimeState = field(default_factory=StepRuntimeState)
    current_speech_text: str | None = None
    selecting_recipe: bool = False


class RecipeCatalog:
    def __init__(self, root: Path) -> None:
        self._root = root

    def list_entries(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        if not self._root.exists():
            return entries
        for path in sorted(self._root.glob("*.json")):
            entries.append({"id": path.stem})
        return entries

    def load(self, recipe_id: str) -> Recipe:
        path = self._root / f"{recipe_id}.json"
        if not path.exists():
            raise ValueError(f"Unknown recipe id: {recipe_id}")
        try:
            return Recipe.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as error:
            raise ValueError(f"Invalid recipe {recipe_id}: {error}") from error

    def best_match(self, inventory_items: list[str]) -> str | None:
        entries = self.list_entries()
        if not entries:
            return None
        if not inventory_items:
            return entries[0]["id"]

        scored: list[tuple[int, str]] = []
        normalized_items = [normalize_inventory_name(item) for item in inventory_items]
        for entry in entries:
            recipe_id = entry["id"]
            haystack = normalize_filename(recipe_id)
            tokens = set(haystack.split())
            score = 0
            for item in normalized_items:
                if not item:
                    continue
                if item in haystack:
                    score += 4
                item_tokens = set(item.split())
                if item_tokens and item_tokens.issubset(tokens):
                    score += 2
                score += sum(1 for token in item_tokens if token in tokens)
            scored.append((score, recipe_id))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return scored[0][1]


class MocktailSessionManager:
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
                    f"(HTTP {response.status_code}): {_response_text(response)}"
                ),
            )

        data = response.json()
        stream_id = str(data.get("stream_id") or "").strip()
        answer_sdp = _extract_answer_sdp(data.get("webrtc"))
        ttl_seconds = _parse_positive_int((data.get("lease") or {}).get("ttl_seconds"))
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
                    f"(HTTP {upstream.status_code}): {_response_text(upstream)}"
                ),
            )

        call_id = _extract_call_id(upstream.headers.get("location"))
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

    async def _run_session_loop(self, session: ControlSession) -> None:
        while True:
            event = await session.queue.get()
            if event.kind == "session.destroy":
                await self._reset_runtime_state(session)
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
                    session, "Something went wrong. Please restart."
                )

    async def _handle_event(self, session: ControlSession, event: SessionEvent) -> None:
        if event.kind == "session.start":
            await self._handle_start(session)
            return
        if event.kind == "session.stop":
            await self._reset_runtime_state(session)
            await self._publish_hud_state(session)
            return
        if event.kind == "debug.step":
            await self._handle_debug_step(session, event.payload)
            return
        if event.kind == "vision.ready":
            await self._maybe_begin_inventory_scan(session)
            return
        if event.kind == "realtime.ready":
            await self._maybe_begin_inventory_scan(session)
            return
        if event.kind == "overshoot.result":
            await self._handle_overshoot_result(session, event.payload)
            return
        if event.kind == "overshoot.closed":
            await self._handle_overshoot_closed(session, event.payload)
            return
        if event.kind == "realtime.closed":
            await self._handle_realtime_closed(session, event.payload)
            return
        if event.kind == "openai.response.done":
            await self._handle_openai_response_done(session, event.payload)
            return
        if event.kind == "openai.error":
            logger.error(
                "session=%s openai error=%s",
                session.session_id,
                event.payload.get("message"),
            )
            if session.phase not in {PHASE_WAITING, PHASE_ERROR}:
                await self._fail_session(
                    session, "OpenAI sideband disconnected. Tap to restart."
                )

    async def _handle_start(self, session: ControlSession) -> None:
        if session.phase not in {PHASE_WAITING, PHASE_ERROR, PHASE_COMPLETED}:
            return
        session.phase = PHASE_CONNECTING
        session.inventory_signature = None
        session.inventory_hits = 0
        session.inventory_items.clear()
        session.recipe = None
        session.step_lookup.clear()
        session.step_index_by_id.clear()
        session.current_step_id = None
        session.step_state = StepRuntimeState()
        session.current_speech_text = None
        session.selecting_recipe = False
        await self._publish_hud_state(session)
        await self._maybe_begin_inventory_scan(session)

    async def _handle_debug_step(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if (
            session.phase not in {PHASE_GUIDING, PHASE_COMPLETED}
            or session.recipe is None
        ):
            return
        direction = str(payload.get("direction") or "").strip().lower()
        if direction not in {"forward", "backward"}:
            return
        if session.current_step_id is None:
            return
        current_index = session.step_index_by_id.get(session.current_step_id)
        if current_index is None:
            return
        delta = 1 if direction == "forward" else -1
        next_index = max(0, min(len(session.recipe.steps) - 1, current_index + delta))
        if next_index == current_index:
            return
        session.phase = PHASE_GUIDING
        session.current_step_id = session.recipe.steps[next_index].id
        await self._enter_step(session, speak_on_enter=True)

    async def _maybe_begin_inventory_scan(self, session: ControlSession) -> None:
        if session.phase != PHASE_CONNECTING:
            return
        if not session.vision_ready or not session.realtime_ready:
            return
        session.phase = PHASE_INVENTORY
        session.inventory_signature = None
        session.inventory_hits = 0
        session.inventory_items.clear()
        session.selecting_recipe = False
        await self._publish_hud_state(session)
        await self._switch_prompt(session, "inventory_scan", INVENTORY_SCAN_PROMPT)

    async def _handle_overshoot_result(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.vision_generation:
            return
        if session.overshoot_stream_id is None:
            return
        if not payload.get("ok", False):
            logger.warning(
                "session=%s overshoot error=%s",
                session.session_id,
                payload.get("error"),
            )
            return

        prompt = str(payload.get("prompt") or "")
        if prompt != session.active_prompt_text:
            return
        parsed = parse_structured_result(payload.get("result"))
        if parsed is None:
            return

        if session.phase == PHASE_INVENTORY:
            await self._handle_inventory_result(session, parsed)
            return
        if session.phase == PHASE_GUIDING and session.recipe is not None:
            await self._evaluate_current_step(session, parsed)

    async def _handle_inventory_result(
        self,
        session: ControlSession,
        result: dict[str, Any],
    ) -> None:
        ingredients = result.get("ingredients")
        if not isinstance(ingredients, list):
            return

        normalized = tuple(
            sorted(
                {
                    normalize_inventory_name(item)
                    for item in ingredients
                    if isinstance(item, str) and normalize_inventory_name(item)
                }
            )
        )
        if not normalized:
            return

        if normalized == session.inventory_signature:
            session.inventory_hits += 1
        else:
            session.inventory_signature = normalized
            session.inventory_hits = 1

        if session.inventory_hits < 2:
            return

        session.inventory_items = list(normalized)
        session.phase = PHASE_RECIPE_SELECTION
        session.selecting_recipe = True
        await self._publish_hud_state(session)
        await self._request_recipe_selection(session)

    async def _request_recipe_selection(self, session: ControlSession) -> None:
        if not session.inventory_items:
            recipe_id = self._recipes.best_match([])
            if recipe_id is not None:
                await self._activate_recipe(session, recipe_id, call_id=None)
            return
        if session.openai_ws is None:
            recipe_id = self._recipes.best_match(session.inventory_items)
            if recipe_id is not None:
                await self._activate_recipe(session, recipe_id, call_id=None)
            return

        ingredient_list = ", ".join(session.inventory_items)
        await self._send_openai_user_text(
            session,
            (
                f"Detected visible ingredients: {ingredient_list}. "
                "Choose the single best recipe filename for these ingredients. "
                "Call list_recipes first, then call activate_recipe. Do not speak."
            ),
        )
        await self._send_openai_event(session, {"type": "response.create"})

    async def _handle_openai_response_done(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.realtime_generation:
            return

        response = payload.get("response") or {}
        output_items = response.get("output") or []
        fn_call = next(
            (
                item
                for item in output_items
                if item.get("type") == "function_call"
                and item.get("status") == "completed"
            ),
            None,
        )

        if fn_call is None:
            if session.phase == PHASE_RECIPE_SELECTION and session.recipe is None:
                recipe_id = self._recipes.best_match(session.inventory_items)
                if recipe_id is not None:
                    await self._activate_recipe(session, recipe_id, call_id=None)
            return

        tool_name = str(fn_call.get("name") or "").strip()
        call_id = str(fn_call.get("call_id") or "").strip()
        args = parse_arguments(fn_call.get("arguments"))

        if tool_name == "list_recipes":
            output = json.dumps(self._recipes.list_entries())
            await self._send_openai_tool_output(
                session,
                call_id=call_id,
                output=output,
                continue_response=True,
            )
            return

        if tool_name == "activate_recipe":
            recipe_id = str(args.get("id") or "").strip()
            if not recipe_id:
                recipe_id = self._recipes.best_match(session.inventory_items) or ""
            await self._activate_recipe(session, recipe_id, call_id=call_id)
            return

        await self._send_openai_tool_output(
            session,
            call_id=call_id,
            output=json.dumps({"error": f"unknown tool {tool_name}"}),
            continue_response=False,
        )

    async def _activate_recipe(
        self,
        session: ControlSession,
        recipe_id: str,
        *,
        call_id: str | None,
    ) -> None:
        if not recipe_id:
            await self._fail_session(
                session, "No recipe matched the scene. Tap to restart."
            )
            return

        try:
            recipe = self._recipes.load(recipe_id)
        except ValueError as error:
            logger.warning(
                "session=%s invalid recipe_id=%s", session.session_id, recipe_id
            )
            if call_id:
                await self._send_openai_tool_output(
                    session,
                    call_id=call_id,
                    output=json.dumps({"error": str(error)}),
                    continue_response=False,
                )
            fallback_id = self._recipes.best_match(session.inventory_items)
            if fallback_id and fallback_id != recipe_id:
                await self._activate_recipe(session, fallback_id, call_id=None)
                return
            await self._fail_session(
                session, "Recipe selection failed. Tap to restart."
            )
            return

        if call_id:
            await self._send_openai_tool_output(
                session,
                call_id=call_id,
                output=json.dumps(
                    {"id": recipe.id, "display_name": recipe.display_name}
                ),
                continue_response=False,
            )

        session.recipe = recipe
        session.step_lookup = {step.id: step for step in recipe.steps}
        session.step_index_by_id = {
            step.id: index for index, step in enumerate(recipe.steps)
        }
        session.current_step_id = recipe.start_step_id
        session.phase = PHASE_GUIDING
        session.selecting_recipe = False
        await self._enter_step(session, speak_on_enter=True)

    async def _enter_step(
        self, session: ControlSession, *, speak_on_enter: bool
    ) -> None:
        if session.recipe is None or session.current_step_id is None:
            return
        step = session.step_lookup.get(session.current_step_id)
        if step is None:
            await self._fail_session(session, "Recipe step is missing. Tap to restart.")
            return
        detector = session.recipe.detectors.get(step.detector_key)
        if detector is None:
            await self._fail_session(
                session, "Recipe detector is missing. Tap to restart."
            )
            return

        session.step_state = StepRuntimeState()
        await self._publish_hud_state(session)
        await self._switch_prompt(session, step.detector_key, detector.prompt)
        if speak_on_enter and step.on_enter_speech:
            await self._speak_line(session, step.on_enter_speech)

    async def _switch_prompt(
        self,
        session: ControlSession,
        detector_key: str,
        prompt: str,
    ) -> None:
        if session.overshoot_stream_id is None:
            session.active_detector_key = detector_key
            session.active_prompt_text = prompt
            return
        if session.active_prompt_text == prompt:
            session.active_detector_key = detector_key
            return

        if session.active_prompt_text is not None:
            response = await self._overshoot_http.patch(
                f"/streams/{session.overshoot_stream_id}/config/prompt",
                json={"prompt": prompt},
            )
            if not response.is_success:
                raise RuntimeError(
                    "Failed to update Overshoot prompt "
                    f"(HTTP {response.status_code}): {_response_text(response)}"
                )

        session.active_detector_key = detector_key
        session.active_prompt_text = prompt
        logger.info(
            "session=%s prompt switched detector=%s",
            session.session_id,
            detector_key,
        )

    async def _evaluate_current_step(
        self,
        session: ControlSession,
        result: dict[str, Any],
    ) -> None:
        if session.recipe is None or session.current_step_id is None:
            return
        step = session.step_lookup.get(session.current_step_id)
        if step is None:
            return
        detector = session.recipe.detectors.get(step.detector_key)
        if detector is None:
            return

        value = extract_result_value(result, step.value_path or detector.field)
        ignored_values = step.ignored_values_list()

        if step.evaluation_mode == "match_value":
            await self._evaluate_match_value(session, step, value, ignored_values)
            return
        if step.evaluation_mode == "numeric_threshold_with_progress_once":
            await self._evaluate_numeric_threshold(session, step, value, ignored_values)
            return
        if step.evaluation_mode == "count_rising_edges_true":
            await self._evaluate_rising_edges(session, step, value)
            return
        if step.evaluation_mode == "enum_progress_once_then_complete":
            await self._evaluate_enum_progress(session, step, value, ignored_values)
            return
        if step.evaluation_mode == "momentary_true_complete":
            await self._evaluate_momentary_true(session, step, value)

    async def _evaluate_match_value(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
        ignored_values: list[Any],
    ) -> None:
        if value in ignored_values:
            session.step_state.last_observed_value = value
            return
        if value == step.expected_value:
            await self._advance_step(
                session, speech=step.success_speech, next_step_id=step.next_step_id
            )
            return
        if step.mismatch_speech:
            should_speak = not step.speak_on_observation_change_only
            if step.speak_on_observation_change_only:
                should_speak = value != session.step_state.last_spoken_observation
            if should_speak:
                session.step_state.last_spoken_observation = value
                await self._speak_line(session, step.mismatch_speech)
        session.step_state.last_observed_value = value

    async def _evaluate_numeric_threshold(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
        ignored_values: list[Any],
    ) -> None:
        if value in ignored_values or not isinstance(value, (int, float)):
            return
        if step.complete_condition and matches_condition(
            step.complete_condition, value
        ):
            await self._advance_step(
                session, speech=step.complete_speech, next_step_id=step.next_step_id
            )
            return
        if (
            step.progress_condition
            and matches_condition(step.progress_condition, value)
            and "progress_once" not in session.step_state.progress_flags
        ):
            session.step_state.progress_flags.add("progress_once")
            if step.progress_once_speech:
                await self._speak_line(session, step.progress_once_speech)

    async def _evaluate_rising_edges(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
    ) -> None:
        observed = bool(value)
        if observed and not session.step_state.previous_boolean_value:
            session.step_state.counter += 1
            milestone = next(
                (
                    item
                    for item in step.milestones
                    if item.count == session.step_state.counter
                ),
                None,
            )
            if milestone is not None:
                if milestone.next_step_id is not None:
                    await self._advance_step(
                        session,
                        speech=milestone.speech,
                        next_step_id=milestone.next_step_id,
                    )
                    session.step_state.previous_boolean_value = observed
                    return
                if milestone.speech:
                    await self._speak_line(session, milestone.speech)
            elif (
                step.target_count is not None
                and session.step_state.counter >= step.target_count
            ):
                await self._advance_step(
                    session, speech=step.complete_speech, next_step_id=step.next_step_id
                )
                session.step_state.previous_boolean_value = observed
                return
        session.step_state.previous_boolean_value = observed

    async def _evaluate_enum_progress(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
        ignored_values: list[Any],
    ) -> None:
        if value in ignored_values:
            return
        if value == step.complete_value:
            await self._advance_step(
                session, speech=step.complete_speech, next_step_id=step.next_step_id
            )
            return
        if (
            value == step.progress_value
            and "progress_once" not in session.step_state.progress_flags
        ):
            session.step_state.progress_flags.add("progress_once")
            if step.progress_once_speech:
                await self._speak_line(session, step.progress_once_speech)

    async def _evaluate_momentary_true(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
    ) -> None:
        if bool(value) is bool(step.complete_on):
            await self._advance_step(
                session, speech=step.complete_speech, next_step_id=step.next_step_id
            )

    async def _advance_step(
        self,
        session: ControlSession,
        *,
        speech: str | None,
        next_step_id: str | None,
    ) -> None:
        if next_step_id is None:
            session.phase = PHASE_COMPLETED
            session.current_step_id = None
            await self._publish_hud_state(session)
            if speech:
                await self._speak_line(session, speech)
            return

        session.phase = PHASE_GUIDING
        session.current_step_id = next_step_id
        await self._enter_step(session, speak_on_enter=speech is None)
        if speech:
            await self._speak_line(session, speech)

    async def _handle_overshoot_closed(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.vision_generation:
            return
        if session.phase in {PHASE_WAITING, PHASE_ERROR}:
            return
        await self._fail_session(session, "Overshoot stream ended. Tap to restart.")

    async def _handle_realtime_closed(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.realtime_generation:
            return
        if session.phase in {PHASE_WAITING, PHASE_ERROR}:
            return
        await self._fail_session(
            session, "Audio guidance disconnected. Tap to restart."
        )

    async def _fail_session(self, session: ControlSession, message: str) -> None:
        await self._reset_runtime_state(session)
        session.phase = PHASE_ERROR
        await self._send_control(
            session,
            {
                "type": "hud.error",
                "message": message,
            },
        )
        await self._publish_hud_state(session)

    async def _reset_runtime_state(self, session: ControlSession) -> None:
        await self._stop_vision_runtime(session)
        await self._stop_realtime_runtime(session)
        session.phase = PHASE_WAITING
        session.active_prompt_text = None
        session.active_detector_key = None
        session.inventory_signature = None
        session.inventory_hits = 0
        session.inventory_items.clear()
        session.recipe = None
        session.step_lookup.clear()
        session.step_index_by_id.clear()
        session.current_step_id = None
        session.step_state = StepRuntimeState()
        session.speech_epoch = 0
        session.current_speech_text = None
        session.selecting_recipe = False

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

    async def _publish_hud_state(self, session: ControlSession) -> None:
        recipe_name = session.recipe.display_name if session.recipe else None
        active_task_id = None
        tasks_payload: list[dict[str, Any]] = []
        completed_task_ids = completed_task_ids_for_session(session)

        if session.recipe is not None and session.current_step_id is not None:
            step = session.step_lookup.get(session.current_step_id)
            if step is not None:
                active_task_id = step.task_id

        if session.recipe is not None:
            for task in session.recipe.tasks:
                tasks_payload.append(
                    {
                        "id": task.id,
                        "text": task.text,
                        "completed": task.id in completed_task_ids,
                    }
                )

        screen = "start" if session.phase == PHASE_WAITING else "running"
        await self._send_control(
            session,
            {
                "type": "hud.state",
                "screen": screen,
                "phase": session.phase,
                "recipe_name": recipe_name,
                "tasks": tasks_payload,
                "active_task_id": active_task_id,
                "speech_epoch": session.speech_epoch,
            },
        )

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
        runtime: Literal["vision", "realtime"],
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
                _response_text(response),
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
                    "description": "Activate the chosen recipe id from the filenames returned by list_recipes.",
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


def completed_task_ids_for_session(session: ControlSession) -> set[str]:
    if session.recipe is None:
        return set()
    if session.phase == PHASE_COMPLETED:
        return {task.id for task in session.recipe.tasks}
    if session.current_step_id is None:
        return set()
    current_index = session.step_index_by_id.get(session.current_step_id)
    if current_index is None:
        return set()
    completed: set[str] = set()
    for task in session.recipe.tasks:
        indices = [
            index
            for index, step in enumerate(session.recipe.steps)
            if step.task_id == task.id
        ]
        if indices and max(indices) < current_index:
            completed.add(task.id)
    return completed


def extract_result_value(result: dict[str, Any], path: str) -> Any:
    current: Any = result
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def matches_condition(condition: RecipeCondition, value: int | float) -> bool:
    if condition.eq is not None and value != condition.eq:
        return False
    if condition.gt is not None and value <= condition.gt:
        return False
    if condition.gte is not None and value < condition.gte:
        return False
    if condition.lt is not None and value >= condition.lt:
        return False
    if condition.lte is not None and value > condition.lte:
        return False
    return True


def parse_structured_result(raw_result: Any) -> dict[str, Any] | None:
    if isinstance(raw_result, dict):
        return raw_result
    if not isinstance(raw_result, str):
        return None
    try:
        data = json.loads(raw_result)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_arguments(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            data = json.loads(raw_args)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def normalize_inventory_name(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_filename(value: str) -> str:
    return normalize_inventory_name(value.replace("-", " "))


def normalize_sdp(raw: str) -> str:
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


def _extract_call_id(location: str | None) -> str | None:
    if not location:
        return None
    return location.rstrip("/").split("/")[-1] or None


def _extract_answer_sdp(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("answer_sdp", "sdp", "answer"):
            value = payload.get(key)
            if isinstance(value, str):
                normalized = normalize_sdp(value)
                if normalized:
                    return normalized
    if isinstance(payload, str):
        return normalize_sdp(payload)
    return ""


def _parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _response_text(response: httpx.Response) -> str:
    try:
        text = response.text.strip()
    except Exception:
        return ""
    return text or ""
