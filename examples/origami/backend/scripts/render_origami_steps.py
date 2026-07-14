from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

BACKEND_DIR = Path(__file__).resolve().parents[1]
STEPS_PATH = BACKEND_DIR / "assets" / "origami_steps.json"
OUTPUT_PATH = BACKEND_DIR / "debug" / "origami_steps.html"


def main() -> None:
    steps = _load_steps(STEPS_PATH)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(_render_page(steps, OUTPUT_PATH), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


def _load_steps(path: Path) -> list[dict[str, str]]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array")

    steps: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"step {index} must be an object")
        item = cast("dict[str, Any]", item)
        step = {
            key: _required_string(item, key, index)
            for key in ("id", "reference_image", "criteria")
        }
        negative_reference_image = _optional_string(
            item, "negative_reference_image", index
        )
        if negative_reference_image is not None:
            step["negative_reference_image"] = negative_reference_image
        steps.append(step)
    return steps


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


def _render_page(steps: list[dict[str, str]], output_path: Path) -> str:
    cards = "\n".join(_render_step(step, output_path) for step in steps)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Origami Fold Criteria</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{
      max-width: 960px;
      margin: 2rem auto;
      padding: 0 1rem;
      font-family: system-ui, sans-serif;
      line-height: 1.5;
    }}
    article {{
      margin: 1.5rem 0;
      padding: 1.25rem;
      border: 1px solid color-mix(in srgb, currentColor 25%, transparent);
      border-radius: 0.75rem;
    }}
    h2 {{ margin: 0 0 1rem; }}
    .content {{
      display: grid;
      grid-template-columns: minmax(160px, 205px) 1fr;
      gap: 1.5rem;
      align-items: start;
    }}
    .references {{ display: grid; gap: 0.75rem; }}
    figure {{ margin: 0; }}
    figcaption {{ margin-bottom: 0.25rem; font-weight: 600; }}
    img {{ width: 100%; height: auto; background: white; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: inherit;
    }}
    @media (max-width: 600px) {{
      .content {{ grid-template-columns: 1fr; }}
      img {{ max-width: 205px; }}
    }}
  </style>
</head>
<body>
  <h1>Origami Fold Criteria</h1>
{cards}
</body>
</html>
"""


def _render_step(step: dict[str, str], output_path: Path) -> str:
    reference_path = STEPS_PATH.parent / step["reference_image"]
    relative_path = Path(os.path.relpath(reference_path, output_path.parent)).as_posix()
    image_url = quote(relative_path, safe="/")
    step_id = html.escape(step["id"])
    criteria = html.escape(step["criteria"])
    references = [
        f'<figure><figcaption>Target</figcaption><img src="{image_url}" '
        f'alt="Target reference image for {step_id}"></figure>'
    ]
    negative_reference_image = step.get("negative_reference_image")
    if negative_reference_image is not None:
        negative_path = STEPS_PATH.parent / negative_reference_image
        negative_relative_path = Path(
            os.path.relpath(negative_path, output_path.parent)
        ).as_posix()
        negative_url = quote(negative_relative_path, safe="/")
        references.append(
            f'<figure><figcaption>Not target</figcaption><img src="{negative_url}" '
            f'alt="Negative reference image for {step_id}"></figure>'
        )
    reference_html = "".join(references)
    return f"""  <article>
    <h2>{step_id}</h2>
    <div class="content">
      <div class="references">{reference_html}</div>
      <pre>{criteria}</pre>
    </div>
  </article>"""


if __name__ == "__main__":
    main()
