from __future__ import annotations

import json
import time
from contextlib import suppress
from typing import Any

import httpx


def _parse_json_object(raw_text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_overshoot_boolean(payload: dict[str, Any]) -> bool | None:
    if payload.get("ok") is False:
        return None
    raw = payload.get("result")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        with suppress(json.JSONDecodeError):
            parsed = json.loads(raw)
            if isinstance(parsed, bool):
                return parsed
            if isinstance(parsed, dict):
                return _first_boolean(parsed)
    if isinstance(raw, dict):
        return _first_boolean(raw)
    return None


def _payload_received_at(payload: dict[str, Any]) -> float:
    value = payload.get("_received_at")
    if isinstance(value, (int, float)):
        return float(value)
    return time.monotonic()


def _first_boolean(payload: dict[str, Any]) -> bool | None:
    for key in ("matches", "match", "result", "value", "ok"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    return None


def _overshoot_payload_for_log(payload: dict[str, Any]) -> dict[str, Any]:
    summarized = dict(payload)
    if "prompt" in summarized:
        summarized["prompt"] = "<active prompt>"
    return summarized


def _extract_answer_sdp(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("answer_sdp", "sdp", "answer"):
            value = payload.get(key)
            if isinstance(value, str):
                return _normalize_sdp(value)
    if isinstance(payload, str):
        return _normalize_sdp(payload)
    return ""


def _normalize_sdp(raw: str) -> str:
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


def _parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _response_text(response: httpx.Response) -> str:
    try:
        return response.text.strip()
    except Exception:
        return ""


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except TypeError:
        return repr(value)
