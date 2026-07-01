from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OrigamiStep:
    id: str
    title: str
    hud_image: str
    reference_image: str
    reference_path: Path
    prompt: str


def load_origami_steps(path: Path) -> list[OrigamiStep]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("origami_steps.json must contain a non-empty array")

    asset_dir = path.parent
    steps: list[OrigamiStep] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"step {index} must be an object")
        steps.append(_parse_step(index, asset_dir, item))
    return steps


def _parse_step(index: int, asset_dir: Path, item: dict[str, Any]) -> OrigamiStep:
    step_id = _required_string(item, "id", index)
    title = _required_string(item, "title", index)
    hud_image = _required_string(item, "hud_image", index)
    reference_image = _required_string(item, "reference_image", index)
    prompt = _required_string(item, "prompt", index)
    reference_path = asset_dir / reference_image
    if not reference_path.exists():
        raise ValueError(f"step {index} reference image not found: {reference_path}")
    return OrigamiStep(
        id=step_id,
        title=title,
        hud_image=hud_image,
        reference_image=reference_image,
        reference_path=reference_path,
        prompt=prompt,
    )


def _required_string(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"step {index} field {key!r} must be a non-empty string")
    return value.strip()
