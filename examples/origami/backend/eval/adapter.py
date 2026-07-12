from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.constants import (
    DEFAULT_OVERSHOOT_API_URL,
    DEFAULT_OVERSHOOT_MODEL,
)
from src.fold_check import (
    compose_fold_check_image,
    fold_check_image_data_url,
    load_fold_check_reference_images,
    load_fold_check_steps,
    parse_fold_check_result,
)
from src.overshoot_client import OvershootClient

IMAGE_LAYOUT_COMPOSITE = "composite"
IMAGE_LAYOUT_SEPARATE = "separate"


def create_evaluator(config: Any) -> Evaluator:
    raw_config = dict(getattr(config, "config", {}) or {})
    backend_dir = Path(__file__).resolve().parents[1]
    steps_path = _path_config(
        raw_config.get("steps_path"),
        default=backend_dir / "assets" / "origami_steps.json",
    )
    overshoot_api_key = _string_config(
        raw_config.get("overshoot_api_key"),
        default=os.getenv("OVERSHOOT_API_KEY", ""),
    )
    if not overshoot_api_key:
        raise RuntimeError("Set OVERSHOOT_API_KEY or adapter_config.overshoot_api_key")
    return Evaluator(
        overshoot_api_key=overshoot_api_key,
        overshoot_api_url=_string_config(
            raw_config.get("overshoot_api_url"),
            default=os.getenv("OVERSHOOT_API_URL", DEFAULT_OVERSHOOT_API_URL),
        ),
        overshoot_model=_string_config(
            raw_config.get("overshoot_model"),
            default=os.getenv("OVERSHOOT_MODEL", DEFAULT_OVERSHOOT_MODEL),
        ),
        steps_path=steps_path,
        jpeg_quality=_int_config(raw_config.get("jpeg_quality"), default=90),
        image_layout=_image_layout_config(raw_config.get("image_layout")),
    )


class Evaluator:
    def __init__(
        self,
        *,
        overshoot_api_key: str,
        overshoot_api_url: str,
        overshoot_model: str,
        steps_path: Path,
        jpeg_quality: int,
        image_layout: str,
    ) -> None:
        self._jpeg_quality = jpeg_quality
        self._image_layout = image_layout
        self._steps = {step.id: step for step in load_fold_check_steps(steps_path)}
        self._reference_images = load_fold_check_reference_images(self._steps.values())
        self._client = OvershootClient(
            api_key=overshoot_api_key,
            model=overshoot_model,
            api_url=overshoot_api_url,
        )

    async def evaluate(self, sample: Any, target: Any) -> bool | None:
        target_id = str(target.id)
        step = self._steps.get(target_id)
        if step is None:
            raise RuntimeError(f"unknown origami target id: {target_id}")
        reference = self._reference_images[target_id].copy()
        if self._image_layout == IMAGE_LAYOUT_SEPARATE:
            thread_id = (
                "glasskit-eval-image-pair-"
                f"{sample.case_name}-{target_id}-{sample.sample_index}"
            )
            completion = await self._client.chat_completion_for_image_pair(
                camera_image_url=fold_check_image_data_url(
                    sample.image,
                    self._jpeg_quality,
                ),
                reference_image_url=fold_check_image_data_url(
                    reference,
                    self._jpeg_quality,
                ),
                thread_id=thread_id,
                prompt=step.criteria,
                log_context=f"eval={thread_id}",
            )
        else:
            thread_id = (
                f"glasskit-eval-{sample.case_name}-{target_id}-{sample.sample_index}"
            )
            image = compose_fold_check_image(sample.image, reference)
            completion = await self._client.chat_completion_for_image(
                image_url=fold_check_image_data_url(image, self._jpeg_quality),
                thread_id=thread_id,
                prompt=step.criteria,
                log_context=f"eval={thread_id}",
            )
        if completion is None:
            raise RuntimeError("Overshoot chat completion failed after retries")
        return parse_fold_check_result(
            {
                "ok": True,
                "result": completion.text,
                "completion_id": completion.completion_id,
            }
        )

    async def close(self) -> None:
        await self._client.close()


def _path_config(raw_value: Any, *, default: Path) -> Path:
    if raw_value is None or str(raw_value).strip() == "":
        return default
    path = Path(str(raw_value)).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def _string_config(raw_value: Any, *, default: str) -> str:
    value = default if raw_value is None else str(raw_value)
    return value.strip()


def _int_config(raw_value: Any, *, default: int) -> int:
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"expected integer adapter config, got {raw_value!r}"
        ) from error


def _image_layout_config(raw_value: Any) -> str:
    value = _string_config(raw_value, default=IMAGE_LAYOUT_COMPOSITE).lower()
    if value not in {IMAGE_LAYOUT_COMPOSITE, IMAGE_LAYOUT_SEPARATE}:
        raise RuntimeError(
            f"image_layout must be 'composite' or 'separate', got {raw_value!r}"
        )
    return value
