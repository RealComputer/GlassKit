from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class OrigamiStep:
    id: str
    title: str
    hud_image: str
    reference_image: str
    reference_path: Path
    negative_reference_image: str | None
    negative_reference_path: Path | None
    criteria: str


def load_origami_steps(path: Path) -> list[OrigamiStep]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("origami_steps.json must contain a non-empty array")

    asset_dir = path.parent
    steps: list[OrigamiStep] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"step {index} must be an object")
        steps.append(_parse_step(index, asset_dir, cast("dict[str, Any]", item)))
    return steps


def _parse_step(index: int, asset_dir: Path, item: dict[str, Any]) -> OrigamiStep:
    step_id = _required_string(item, "id", index)
    title = _required_string(item, "title", index)
    hud_image = _required_string(item, "hud_image", index)
    reference_image = _required_string(item, "reference_image", index)
    negative_reference_image = _optional_string(item, "negative_reference_image", index)
    criteria = _required_string(item, "criteria", index)
    reference_path = asset_dir / reference_image
    if not reference_path.exists():
        raise ValueError(f"step {index} reference image not found: {reference_path}")
    negative_reference_path = (
        asset_dir / negative_reference_image
        if negative_reference_image is not None
        else None
    )
    if negative_reference_path is not None and not negative_reference_path.exists():
        raise ValueError(
            f"step {index} negative reference image not found: "
            f"{negative_reference_path}"
        )
    return OrigamiStep(
        id=step_id,
        title=title,
        hud_image=hud_image,
        reference_image=reference_image,
        reference_path=reference_path,
        negative_reference_image=negative_reference_image,
        negative_reference_path=negative_reference_path,
        criteria=criteria,
    )


def _required_string(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"step {index} field {key!r} must be a non-empty string")
    return value.strip()


def _optional_string(item: dict[str, Any], key: str, index: int) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"step {index} field {key!r} must be a non-empty string")
    return value.strip()
