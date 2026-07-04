from __future__ import annotations

import math
from typing import Any


def json_value_error(value: Any, *, label: str = "value") -> str | None:
    return _json_value_error(value, path=label, seen=set())


def _json_value_error(value: Any, *, path: str, seen: set[int]) -> str | None:
    if value is None or isinstance(value, bool | str):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return f"{path} must be finite"
        return None
    if isinstance(value, list):
        value_id = id(value)
        if value_id in seen:
            return f"{path} must not contain cycles"
        seen.add(value_id)
        for index, item in enumerate(value):
            if error := _json_value_error(item, path=f"{path}[{index}]", seen=seen):
                return error
        seen.remove(value_id)
        return None
    if isinstance(value, dict):
        value_id = id(value)
        if value_id in seen:
            return f"{path} must not contain cycles"
        seen.add(value_id)
        for key, item in value.items():
            if not isinstance(key, str):
                return f"{path} keys must be strings"
            if error := _json_value_error(item, path=_child_path(path, key), seen=seen):
                return error
        seen.remove(value_id)
        return None
    return f"{path} must be JSON-like; got {type(value).__name__}"


def _child_path(parent: str, key: str) -> str:
    if key.isidentifier():
        return f"{parent}.{key}"
    return f"{parent}[{key!r}]"
