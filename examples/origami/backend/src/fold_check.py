from __future__ import annotations

import base64
import io
from collections.abc import Iterable
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
    *,
    negative_reference: Image.Image | None = None,
) -> Image.Image:
    return _compose_reference_image(
        camera,
        reference,
        label,
        negative_reference=negative_reference,
    )


def fold_check_stream_image_url(stream_id: str) -> str:
    return f"ovs://streams/{stream_id}?frame_index=-1"


def fold_check_image_data_url(image: Image.Image, jpeg_quality: int = 90) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer,
        format="JPEG",
        quality=max(1, min(100, jpeg_quality)),
        optimize=True,
    )
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def parse_fold_check_result(payload: dict[str, Any]) -> bool | None:
    return _parse_fold_check_boolean(payload)


def load_fold_check_reference_images(
    steps: Iterable[OrigamiStep],
) -> dict[str, Image.Image]:
    images: dict[str, Image.Image] = {}
    for step in steps:
        with Image.open(step.reference_path) as image:
            images[step.id] = image.convert("RGB")
    return images


def load_fold_check_negative_reference_images(
    steps: Iterable[OrigamiStep],
) -> dict[str, Image.Image]:
    images: dict[str, Image.Image] = {}
    for step in steps:
        if step.negative_reference_path is None:
            continue
        with Image.open(step.negative_reference_path) as image:
            images[step.id] = image.convert("RGB")
    return images


def load_fold_check_steps(path: Path) -> list[OrigamiStep]:
    return load_origami_steps(path)
