from __future__ import annotations

from typing import Any

LIVE_FOLD_CHECK_SYSTEM_PROMPT = (
    "You verify origami fold completion from a live camera view. Return exactly true "
    "or false with no explanation."
)

RECORDED_FOLD_CHECK_SYSTEM_PROMPT = (
    "You verify origami fold completion from a camera view. Return exactly true or "
    "false with no explanation."
)

FOLD_CHECK_RESPONSE_INSTRUCTIONS = (
    "Return exactly true or false. Do not include any other text."
)


def fold_check_messages(
    *,
    prompt: str,
    image_url: str,
    system_prompt: str,
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"{prompt}\n\n{FOLD_CHECK_RESPONSE_INSTRUCTIONS}",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ],
        },
    ]
