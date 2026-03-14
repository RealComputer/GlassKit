from __future__ import annotations

from typing import Literal

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
    "Return the visible ingredient list on the table as an `ingredients` array "
    "containing up to 4 clearly visible ingredient names. "
    "Prefer items placed around the center of the screen. Use short "
    'lowercase names like "orange juice", "gatorade", or "lime".'
)
GENERAL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ingredients": {
            "type": "array",
            "items": {"type": "string"},
        },
        "color": {"type": "string"},
        "state": {"type": "string"},
        "flag": {"type": "boolean"},
        "level": {
            "anyOf": [
                {"type": "integer", "minimum": 0, "maximum": 10},
                {"type": "string"},
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

PHASE_WAITING = "WAITING_FOR_START"
PHASE_CONNECTING = "CONNECTING"
PHASE_INVENTORY = "INVENTORY_SCAN"
PHASE_RECIPE_SELECTION = "RECIPE_SELECTION"
PHASE_GUIDING = "GUIDING"
PHASE_COMPLETED = "COMPLETED"
PHASE_ERROR = "ERROR"

RuntimeKind = Literal["vision", "realtime"]
EvaluationMode = Literal[
    "match_value",
    "numeric_threshold_with_progress_once",
    "count_rising_edges_true",
    "enum_progress_once_then_complete",
    "momentary_true_complete",
]
