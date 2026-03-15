from __future__ import annotations

import json
from typing import Any

import httpx

from recipe_catalog import RecipeCondition
from session_constants import INVENTORY_SCAN_PROMPT
from session_types import ControlSession


def completed_task_ids_for_session(session: ControlSession) -> set[str]:
    if session.recipe is None:
        return set()
    if session.phase == "COMPLETED":
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


def matches_overshoot_prompt(expected_prompt: str, result_prompt: str) -> bool:
    if result_prompt == expected_prompt:
        return True
    if not expected_prompt or not result_prompt:
        return False
    return result_prompt.startswith(expected_prompt)


def detector_key_for_overshoot_prompt(
    session: ControlSession, prompt: str
) -> str | None:
    if session.active_prompt_text and matches_overshoot_prompt(
        session.active_prompt_text, prompt
    ):
        return session.active_detector_key
    if matches_overshoot_prompt(INVENTORY_SCAN_PROMPT, prompt):
        return "inventory_scan"
    if session.recipe is None:
        return None
    for detector_key, detector in session.recipe.detectors.items():
        if matches_overshoot_prompt(detector.prompt, prompt):
            return detector_key
    return None


def overshoot_payload_for_log(
    session: ControlSession, payload: dict[str, Any]
) -> dict[str, Any]:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return payload
    detector_key = detector_key_for_overshoot_prompt(session, prompt)
    if detector_key is None:
        return payload
    summarized_payload = dict(payload)
    summarized_payload.pop("prompt", None)
    summarized_payload["prompt_key"] = detector_key
    return summarized_payload


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


def extract_call_id(location: str | None) -> str | None:
    if not location:
        return None
    return location.rstrip("/").split("/")[-1] or None


def extract_answer_sdp(payload: Any) -> str:
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


def parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def response_text(response: httpx.Response) -> str:
    try:
        text = response.text.strip()
    except Exception:
        return ""
    return text or ""
