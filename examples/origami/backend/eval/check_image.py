from __future__ import annotations

import argparse
from pathlib import Path

from google import genai
from PIL import Image

from eval.generate_case import BACKEND_DIR, label_camera_image
from src.fold_check import load_fold_check_reference_images, load_fold_check_steps


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check individual camera images with the eval Gemini prompt."
    )
    parser.add_argument("--target", required=True, help="Origami step id, e.g. step_1.")
    parser.add_argument("images", nargs="+", type=Path, help="Camera image paths.")
    args = parser.parse_args()

    steps = {
        step.id: step
        for step in load_fold_check_steps(BACKEND_DIR / "assets" / "origami_steps.json")
    }
    if args.target not in steps:
        parser.error(f"unknown target: {args.target}")

    step = steps[args.target]
    reference = load_fold_check_reference_images([step])[args.target]
    client = genai.Client()
    for image_path in args.images:
        with Image.open(image_path) as camera_image:
            result = label_camera_image(
                client,
                camera_image=camera_image.convert("RGB"),
                reference_image=reference,
                prompt=step.criteria,
                log_context=str(image_path),
            )
        print(f"{image_path}: {str(result.value).lower()} ({result.response_text!r})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
