from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from av import VideoFrame
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .constants import (
    DEMO_BACKGROUND_BRIGHTNESS,
    HUD_DENSITY,
    HUD_DIM_GREEN,
    HUD_GREEN,
    HUD_HEIGHT,
    HUD_WIDTH,
    PHASE_WAITING,
)

logger = logging.getLogger("uvicorn.error")


def _compose_reference_image(
    camera: Image.Image,
    reference: Image.Image,
    label: str,
) -> Image.Image:
    base = camera.convert("RGB")
    width, height = base.size
    header_height = max(80, height // 4)
    reference_size = int(header_height * 0.75)
    margin = max(20, width // 24)
    gap = max(24, width // 20)

    header = Image.new("RGB", (width, header_height), "white")
    draw = ImageDraw.Draw(header)
    max_text_width = width - (2 * margin) - gap - reference_size
    font = _fit_font(draw, label, max_text_width, max(18, header_height // 3))
    bbox = draw.textbbox((0, 0), label, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    group_width = text_width + gap + reference_size
    text_x = max(margin, (width - group_width) // 2)
    image_x = min(width - margin - reference_size, text_x + text_width + gap)
    text_y = (header_height - text_height) // 2 - bbox[1]
    image_y = (header_height - reference_size) // 2
    draw.text((text_x, text_y), label, fill="black", font=font)

    reference = reference.copy()
    reference.thumbnail((reference_size, reference_size), Image.Resampling.LANCZOS)
    image_box = Image.new("RGB", (reference_size, reference_size), "white")
    image_box.paste(
        reference,
        (
            (reference_size - reference.width) // 2,
            (reference_size - reference.height) // 2,
        ),
    )
    header.paste(image_box, (int(image_x), int(image_y)))
    base.paste(header, (0, 0))
    return base


def _compose_demo_image(
    *,
    base: Image.Image,
    hud_state: dict[str, Any],
    hud_image: Image.Image | None,
) -> Image.Image:
    image = ImageEnhance.Brightness(base.convert("RGB")).enhance(
        DEMO_BACKGROUND_BRIGHTNESS
    )
    hud = _backend_hud_image(hud_state, hud_image)
    hud = _fit_hud_to_canvas(hud, image.size)
    image_rgba = image.convert("RGBA")
    image_rgba.alpha_composite(_green_hud_overlay(hud))
    return image_rgba.convert("RGB")


def _fit_hud_to_canvas(hud: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, "black")
    fitted = ImageOps.contain(hud, size, Image.Resampling.LANCZOS)
    canvas.paste(
        fitted,
        (
            (size[0] - fitted.width) // 2,
            (size[1] - fitted.height) // 2,
        ),
    )
    return canvas


def _backend_hud_image(
    hud_state: dict[str, Any],
    hud_image: Image.Image | None,
) -> Image.Image:
    image = Image.new("RGB", (HUD_WIDTH, HUD_HEIGHT), "black")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(_sp(20))
    step_font = _load_font(_sp(15))
    hint_font = _load_font(_sp(17))
    controls_font = _load_font(_sp(12))

    title_bbox = _draw_centered_text(
        draw,
        "Origami Guide",
        center_x=HUD_WIDTH // 2,
        y=_dp(25),
        font=title_font,
        fill=HUD_GREEN,
    )

    if hud_state.get("screen") == "start":
        hint_y = title_bbox[3] + _dp(38)
        _draw_centered_text(
            draw,
            "Double tap temple to start",
            center_x=HUD_WIDTH // 2,
            y=hint_y,
            font=hint_font,
            fill=HUD_GREEN,
        )
        _draw_centered_lines(
            draw,
            ["Double tap temple to start"],
            center_x=HUD_WIDTH // 2,
            bottom=HUD_HEIGHT - _dp(16),
            font=controls_font,
            fill=HUD_GREEN,
            line_gap=3,
        )
        return image

    draw.text(
        (_dp(18), _dp(68)),
        f"Step {hud_state.get('step_number', 1)}/{hud_state.get('step_count', 7)}",
        fill=HUD_GREEN,
        font=step_font,
    )

    if hud_image is not None:
        guide = _green_hud_asset(hud_image)
        guide.thumbnail((HUD_WIDTH - 2 * _dp(18), 180), Image.Resampling.LANCZOS)
        image.paste(
            guide,
            (
                (HUD_WIDTH - guide.width) // 2,
                _dp(94) + (180 - guide.height) // 2,
            ),
        )

    message = str(hud_state.get("message") or "")
    if message:
        message_size = _sp(21)
        fitted = _fit_font(draw, message, HUD_WIDTH - 36, message_size)
        _draw_centered_text(
            draw,
            message,
            center_x=HUD_WIDTH // 2,
            y=_dp(206),
            font=fitted,
            fill=HUD_GREEN,
        )

    auto_enabled = bool(hud_state.get("auto_check_enabled", True))
    controls = (
        ["Auto check on", "Swipe: previous/next | Double tap: reset"]
        if auto_enabled
        else ["Auto check off", "Swipe: previous/next | Double tap: reset"]
    )
    _draw_centered_lines(
        draw,
        controls,
        center_x=HUD_WIDTH // 2,
        bottom=HUD_HEIGHT - _dp(16),
        font=controls_font,
        fill=HUD_GREEN,
        line_gap=16,
    )
    return image


def _demo_placeholder(message: str) -> Image.Image:
    image = Image.new("RGB", (1024, 768), "black")
    draw = ImageDraw.Draw(image)
    font = _load_font(44)
    bbox = draw.textbbox((0, 0), message, font=font)
    draw.text(
        ((1024 - (bbox[2] - bbox[0])) // 2, (768 - (bbox[3] - bbox[1])) // 2),
        message,
        fill=HUD_DIM_GREEN,
        font=font,
    )
    return image


def _green_hud_asset(image: Image.Image) -> Image.Image:
    source = image.convert("RGBA")
    luminance = source.convert("L")
    colorized = ImageOps.colorize(luminance, black=(0, 0, 0), white=HUD_GREEN)
    colorized.putalpha(source.getchannel("A"))
    background = Image.new("RGBA", source.size, (0, 0, 0, 255))
    background.alpha_composite(colorized)
    return background.convert("RGB")


def _green_hud_overlay(image: Image.Image) -> Image.Image:
    source = image.convert("RGB")
    alpha = source.convert("L").point(lambda value: min(245, value * 3))
    glow_alpha = alpha.filter(ImageFilter.GaussianBlur(radius=2)).point(
        lambda value: min(90, value)
    )
    glow = Image.new("RGBA", source.size, (*HUD_GREEN, 0))
    glow.putalpha(glow_alpha)
    sharp = Image.new("RGBA", source.size, (*HUD_GREEN, 0))
    sharp.putalpha(alpha)
    glow.alpha_composite(sharp)
    return glow


def _dp(value: int) -> int:
    return round(value * HUD_DENSITY)


def _sp(value: int) -> int:
    return round(value * HUD_DENSITY)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    center_x: int,
    y: int,
    font: Any,
    fill: tuple[int, int, int],
) -> tuple[int, int, int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    x = center_x - width // 2 - bbox[0]
    draw.text((x, y - bbox[1]), text, fill=fill, font=font)
    rendered = draw.textbbox((x, y - bbox[1]), text, font=font)
    return (
        int(rendered[0]),
        int(rendered[1]),
        int(rendered[2]),
        int(rendered[3]),
    )


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    *,
    center_x: int,
    bottom: int,
    font: Any,
    fill: tuple[int, int, int],
    line_gap: int,
) -> None:
    metrics = [draw.textbbox((0, 0), line, font=font) for line in lines]
    heights = [bbox[3] - bbox[1] for bbox in metrics]
    total_height = sum(heights) + line_gap * max(0, len(lines) - 1)
    y = bottom - total_height
    for line, bbox, height in zip(lines, metrics, heights, strict=True):
        width = bbox[2] - bbox[0]
        x = center_x - width // 2 - bbox[0]
        draw.text((x, y - bbox[1]), line, fill=fill, font=font)
        y += height + line_gap


def _empty_hud_payload(auto_check_available: bool = True) -> dict[str, Any]:
    return {
        "type": "hud.state",
        "screen": "start",
        "phase": PHASE_WAITING,
        "step_index": 0,
        "step_number": 1,
        "step_count": 7,
        "step_id": "step_1",
        "step_title": "Step 1",
        "hud_image": "origami_step_1",
        "auto_check_enabled": auto_check_available,
        "auto_check_available": auto_check_available,
        "true_streak": 0,
        "message": "",
    }


def _frame_to_image(
    frame: VideoFrame, *, fallback_size: tuple[int, int]
) -> Image.Image:
    try:
        return frame.to_image().convert("RGB")
    except Exception:
        logger.exception("failed to convert video frame to image")
        return Image.new("RGB", fallback_size, "black")


def _save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, format="JPEG", quality=90, optimize=True)


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
) -> Any:
    size = start_size
    while size > 10:
        font = _load_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return _load_font(size)


def _load_font(size: int) -> Any:
    for path in (
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ):
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()
