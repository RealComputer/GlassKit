from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from websockets.asyncio.client import ClientConnection

from recipe_catalog import Recipe, RecipeStep
from session_constants import PHASE_WAITING


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
    openai_response_active: bool = False
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
