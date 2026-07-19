from __future__ import annotations

from pathlib import Path
from typing import Any

from google import genai

from eval.gemini import BACKEND_DIR, label_camera_image
from src.fold_check import load_fold_check_reference_images, load_fold_check_steps


def create_evaluator(config: Any) -> Evaluator:
    raw_config = dict(getattr(config, "config", {}) or {})
    steps_path = _path_config(
        raw_config.get("steps_path"),
        default=BACKEND_DIR / "assets" / "origami_steps.json",
    )
    return Evaluator(steps_path=steps_path)


class Evaluator:
    def __init__(self, *, steps_path: Path) -> None:
        self._steps = {step.id: step for step in load_fold_check_steps(steps_path)}
        self._reference_images = load_fold_check_reference_images(self._steps.values())

    def evaluate(self, sample: Any, target: Any) -> bool:
        target_id = str(target.id)
        step = self._steps.get(target_id)
        if step is None:
            raise RuntimeError(f"unknown origami target id: {target_id}")
        result = label_camera_image(
            genai.Client(),
            camera_image=sample.image,
            reference_image=self._reference_images[target_id].copy(),
            prompt=step.criteria,
            log_context=(f"seed={sample.case_name}/{target_id}/{sample.sample_index}"),
        )
        return result.value


def _path_config(raw_value: Any, *, default: Path) -> Path:
    if raw_value is None or str(raw_value).strip() == "":
        return default
    path = Path(str(raw_value)).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve()
