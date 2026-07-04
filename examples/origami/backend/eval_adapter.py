from __future__ import annotations

import asyncio
import base64
import io
import os
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from src.constants import (
    DEFAULT_OVERSHOOT_API_URL,
    DEFAULT_OVERSHOOT_MODEL,
    OVERSHOOT_CHAT_COMPLETION_TIMEOUT_SECONDS,
)
from src.fold_check import (
    compose_fold_check_image,
    load_fold_check_steps,
    parse_fold_check_result,
)
from src.origami_config import OrigamiStep
from src.overshoot_prompts import RECORDED_FOLD_CHECK_SYSTEM_PROMPT, fold_check_messages

_CHAT_COMPLETION_RETRY_DELAYS = (0.0, 0.5, 1.0, 2.0)


def create_evaluator(config: Any) -> OrigamiFoldCheckEvaluator:
    raw_config = dict(getattr(config, "config", {}) or {})
    backend_dir = Path(__file__).resolve().parent
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
    return OrigamiFoldCheckEvaluator(
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
    )


class OrigamiFoldCheckEvaluator:
    def __init__(
        self,
        *,
        overshoot_api_key: str,
        overshoot_api_url: str,
        overshoot_model: str,
        steps_path: Path,
        jpeg_quality: int,
    ) -> None:
        self._overshoot_model = overshoot_model
        self._jpeg_quality = jpeg_quality
        self._steps = {step.id: step for step in load_fold_check_steps(steps_path)}
        self._reference_images = _load_reference_images(self._steps)
        self._http = httpx.AsyncClient(
            base_url=overshoot_api_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"Authorization": f"Bearer {overshoot_api_key}"},
        )

    async def evaluate_many(self, samples: list[Any], target: Any) -> list[bool | None]:
        results: list[bool | None] = []
        for sample in samples:
            results.append(await self.evaluate(sample, target))
        return results

    async def evaluate(self, sample: Any, target: Any) -> bool | None:
        target_id = str(target.id)
        step = self._steps.get(target_id)
        if step is None:
            raise RuntimeError(f"unknown origami target id: {target_id}")
        reference = self._reference_images[target_id].copy()
        image = compose_fold_check_image(sample.image, reference)
        completion = await self._post_fold_check_completion(
            prompt=step.prompt,
            image=image,
            thread_id=(f"gk-eval-{sample.case_name}-{target_id}-{sample.sample_index}"),
        )
        text = _chat_completion_text(completion)
        return parse_fold_check_result({"ok": True, "result": text})

    async def close(self) -> None:
        await self._http.aclose()

    async def _post_fold_check_completion(
        self,
        *,
        prompt: str,
        image: Image.Image,
        thread_id: str,
    ) -> dict[str, Any]:
        payload = {
            "model": self._overshoot_model,
            "thread_id": thread_id,
            "temperature": 0,
            "max_tokens": 8,
            "messages": fold_check_messages(
                prompt=prompt,
                image_url=_image_data_url(image, self._jpeg_quality),
                system_prompt=RECORDED_FOLD_CHECK_SYSTEM_PROMPT,
            ),
        }
        for attempt, delay in enumerate(_CHAT_COMPLETION_RETRY_DELAYS, start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await self._http.post(
                    "/chat/completions",
                    json=payload,
                    timeout=OVERSHOOT_CHAT_COMPLETION_TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as error:
                if attempt == len(_CHAT_COMPLETION_RETRY_DELAYS):
                    raise RuntimeError(f"Overshoot request failed: {error}") from error
                continue
            if response.is_success:
                data = response.json()
                return data if isinstance(data, dict) else {}
            if response.status_code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(
                    "Overshoot chat completion failed "
                    f"(HTTP {response.status_code}): {_response_text(response)}"
                )
        raise RuntimeError("Overshoot chat completion failed after retries")


def _load_reference_images(steps: dict[str, OrigamiStep]) -> dict[str, Image.Image]:
    images: dict[str, Image.Image] = {}
    for step_id, step in steps.items():
        with Image.open(step.reference_path) as image:
            images[step_id] = image.convert("RGB")
    return images


def _image_data_url(image: Image.Image, jpeg_quality: int) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer,
        format="JPEG",
        quality=max(1, min(100, jpeg_quality)),
        optimize=True,
    )
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _chat_completion_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    return ""


def _response_text(response: httpx.Response) -> str:
    try:
        return response.text.strip()
    except Exception:
        return ""


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
