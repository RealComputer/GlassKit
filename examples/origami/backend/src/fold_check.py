from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .origami_config import OrigamiStep, load_origami_steps
from .payload_utils import _parse_fold_check_boolean
from .rendering import _compose_reference_image


def compose_fold_check_image(
    camera: Image.Image,
    reference: Image.Image,
    label: str = "Reference shape",
) -> Image.Image:
    return _compose_reference_image(camera, reference, label)


def parse_fold_check_result(payload: dict[str, Any]) -> bool | None:
    return _parse_fold_check_boolean(payload)


def load_fold_check_steps(path: Path) -> list[OrigamiStep]:
    return load_origami_steps(path)
