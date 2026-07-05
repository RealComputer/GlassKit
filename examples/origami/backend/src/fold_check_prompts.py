from __future__ import annotations

from typing import Any

FOLD_CHECK_SYSTEM_PROMPT = (
    "You verify origami fold completion from a single image. The top of the image "
    "contains the reference shape, and the paper model below it is the candidate "
    "fold. Compare the candidate to the reference shape and the step-specific "
    "criteria. If the candidate is missing, mostly outside the image, too blurry, "
    "or obstructed enough that the relevant folds cannot be judged, return exactly "
    "false. Return exactly true when the candidate satisfies the criteria; "
    "otherwise return exactly false. Do not include any other text."
)

FOLD_CHECK_CHAT_TEMPERATURE = 0
FOLD_CHECK_CHAT_MAX_TOKENS = 8


def fold_check_completion_payload(
    *,
    model: str,
    thread_id: str,
    prompt: str,
    image_url: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "thread_id": thread_id,
        "temperature": FOLD_CHECK_CHAT_TEMPERATURE,
        "max_tokens": FOLD_CHECK_CHAT_MAX_TOKENS,
        "messages": fold_check_messages(
            prompt=prompt,
            image_url=image_url,
        ),
    }


def fold_check_messages(
    *,
    prompt: str,
    image_url: str,
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": FOLD_CHECK_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ],
        },
    ]
