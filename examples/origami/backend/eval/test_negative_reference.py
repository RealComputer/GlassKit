from pathlib import Path

from PIL import Image

from src.fold_check import compose_fold_check_image, load_fold_check_steps
from src.fold_check_prompts import (
    FOLD_CHECK_NEGATIVE_EXEMPLAR_SYSTEM_PROMPT,
    FOLD_CHECK_SYSTEM_PROMPT,
    fold_check_system_prompt,
)


def test_step_six_configures_step_five_as_negative_reference() -> None:
    steps_path = Path(__file__).resolve().parents[1] / "assets/origami_steps.json"
    steps = {step.id: step for step in load_fold_check_steps(steps_path)}

    assert steps["step_6"].negative_reference_image == "ref-imgs/5.jpg"
    assert steps["step_6"].negative_reference_path == (
        steps_path.parent / "ref-imgs/5.jpg"
    )
    assert all(
        step.negative_reference_path is None
        for step_id, step in steps.items()
        if step_id != "step_6"
    )


def test_negative_reference_header_preserves_camera_below_top_quarter() -> None:
    camera = Image.new("RGB", (400, 320), (20, 40, 60))
    target = Image.new("RGB", (50, 50), (220, 10, 10))
    negative = Image.new("RGB", (50, 50), (10, 10, 220))

    composed = compose_fold_check_image(
        camera,
        target,
        negative_reference=negative,
    )

    header_height = max(80, camera.height // 4)
    assert composed.size == camera.size
    assert composed.crop((0, header_height, camera.width, camera.height)).tobytes() == (
        camera.crop((0, header_height, camera.width, camera.height)).tobytes()
    )
    header_colors = {
        color
        for _, color in composed.crop((0, 0, camera.width, header_height)).getcolors(
            maxcolors=camera.width * header_height
        )
        or []
    }
    assert target.getpixel((0, 0)) in header_colors
    assert negative.getpixel((0, 0)) in header_colors


def test_negative_exemplar_prompt_selection_is_opt_in() -> None:
    assert (
        fold_check_system_prompt(has_negative_exemplar=False)
        == FOLD_CHECK_SYSTEM_PROMPT
    )
    assert (
        fold_check_system_prompt(has_negative_exemplar=True)
        == FOLD_CHECK_NEGATIVE_EXEMPLAR_SYSTEM_PROMPT
    )
