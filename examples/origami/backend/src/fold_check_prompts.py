from __future__ import annotations

from typing import Any

FOLD_CHECK_SYSTEM_PROMPT = "You verify whether an origami model matches a reference in a single image. The reference shape is at the top of the image. The area below it is a camera frame that may contain the candidate paper model. Compare any visible candidate paper model in the camera frame with both the reference shape and the supplied criteria. Return exactly false if the candidate is missing, any part of the paper model is cut off by the frame edge, too blurry, or too obstructed to judge the relevant folds. Return exactly true only when the candidate satisfies both the reference and the criteria; otherwise return exactly false. Do not include any other text."

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
