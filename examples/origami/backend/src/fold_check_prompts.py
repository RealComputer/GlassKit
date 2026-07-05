from __future__ import annotations

from typing import Any

FOLD_CHECK_SYSTEM_PROMPT = "You verify origami fold completion from an image. The top of the image contains the reference shape, and the paper model below it is the candidate fold. Compare the candidate to the reference shape and the criteria. If the candidate is missing, partialy outside the frame, too blurry, obstructed enough that the relevant folds cannot be judged, or fold state doesn't match the reference and the criteria, return exactly false. When the candidate satisfies them, return exactly true. Do not include any other text."

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
                    "text": f"Criteria: {prompt}",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ],
        },
    ]
