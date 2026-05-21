#!/usr/bin/env python3
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_FONT = Path("/System/Library/Fonts/Supplemental/Arial.ttf")


def run(command):
    subprocess.run(command, check=True)


def video_size(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def load_font(font_path, size):
    if font_path:
        return ImageFont.truetype(str(font_path), size=size)
    if DEFAULT_FONT.exists():
        return ImageFont.truetype(str(DEFAULT_FONT), size=size)
    return ImageFont.load_default(size=size)


def fit_label(draw, label, font_path, font_size, max_width):
    size = font_size
    while size > 10:
        font = load_font(font_path, size)
        bbox = draw.textbbox((0, 0), label, font=font)
        text_width = bbox[2] - bbox[0]
        if text_width <= max_width:
            return font, bbox
        size -= 2

    font = load_font(font_path, size)
    return font, draw.textbbox((0, 0), label, font=font)


def make_header(
    width,
    height,
    reference_image,
    label,
    font_path,
    font_size,
    gap,
    margin,
):
    header_height = height // 4
    reference_size = int(header_height * 0.75)

    header = Image.new("RGB", (width, header_height), "white")
    draw = ImageDraw.Draw(header)
    max_text_width = width - (2 * margin) - gap - reference_size
    font, bbox = fit_label(draw, label, font_path, font_size, max_text_width)

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    group_width = text_width + gap + reference_size
    text_x = max(margin, (width - group_width) // 2)
    image_x = min(width - margin - reference_size, text_x + text_width + gap)
    text_y = (header_height - text_height) // 2 - bbox[1]
    image_y = (header_height - reference_size) // 2

    draw.text((text_x, text_y), label, fill="black", font=font)

    with Image.open(reference_image) as reference:
        reference = reference.convert("RGB")
        reference.thumbnail((reference_size, reference_size), Image.Resampling.LANCZOS)
        image_box = Image.new("RGB", (reference_size, reference_size), "white")
        paste_x = (reference_size - reference.width) // 2
        paste_y = (reference_size - reference.height) // 2
        image_box.paste(reference, (paste_x, paste_y))
        header.paste(image_box, (image_x, image_y))

    return header


def render_video(source, reference_image, output, label, font, font_size, gap, margin):
    width, height = video_size(source)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".png", dir=output.parent, delete=False
    ) as header_file:
        header_path = Path(header_file.name)

    try:
        header = make_header(
            width=width,
            height=height,
            reference_image=reference_image,
            label=label,
            font_path=font,
            font_size=font_size,
            gap=gap,
            margin=margin,
        )
        header.save(header_path)

        run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-i",
                str(header_path),
                "-filter_complex",
                "[0:v][1:v]overlay=0:0:eof_action=repeat[v]",
                "-map",
                "[v]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
    finally:
        header_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Create a video with a white top-quarter reference header."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("reference_image", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--label", default="Reference shape")
    parser.add_argument("--font", type=Path)
    parser.add_argument("--font-size", type=int, default=52)
    parser.add_argument("--gap", type=int, default=56)
    parser.add_argument("--margin", type=int, default=48)
    args = parser.parse_args()

    render_video(
        source=args.source,
        reference_image=args.reference_image,
        output=args.output,
        label=args.label,
        font=args.font,
        font_size=args.font_size,
        gap=args.gap,
        margin=args.margin,
    )


if __name__ == "__main__":
    main()
