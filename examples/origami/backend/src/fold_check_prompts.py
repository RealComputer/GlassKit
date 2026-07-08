from __future__ import annotations

from typing import Any

FOLD_CHECK_SYSTEM_PROMPT = "You verify whether an origami model matches a reference in a single image. The reference shape is at the top of the image. The area below it is a camera frame that may contain the candidate paper model. Only judge a candidate paper model that is resting on a surface or being held in a hand. If multiple candidates are visible, judge the largest candidate near the center of the camera frame and ignore smaller, background, or off-center candidates. Compare the selected candidate primarily with the reference shape, using the supplied criteria as visual cues. The candidate does not need to match the reference orientation exactly, but it should be roughly aligned; modest tilt, perspective, or hand rotation is fine, but sideways or upside-down candidates are not. Return exactly false if the candidate is missing, any part of the paper model is cut off by the frame edge, too blurry, or too obstructed to judge the relevant folds. Return exactly true only when the selected candidate matches the reference shape and is consistent with the criteria; otherwise return exactly false. Do not include any other text."
FOLD_CHECK_CRITERIA_PREFIX = "Criteria: "

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
                    "text": fold_check_criteria_text(prompt),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ],
        },
    ]


def fold_check_criteria_text(prompt: str) -> str:
    return f"{FOLD_CHECK_CRITERIA_PREFIX}{prompt}"
