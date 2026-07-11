from __future__ import annotations

from typing import Any

FOLD_CHECK_SYSTEM_PROMPT = "You verify whether an origami model matches a reference in a single image. The reference shape is at the top of the image. The area below it is a camera frame that may contain the candidate paper model. Only judge a candidate paper model that is resting on a surface or being held in a hand. If multiple candidates are visible, judge the largest candidate near the center of the camera frame and ignore smaller, background, or off-center candidates. Compare the selected candidate primarily with the reference shape, using the supplied criteria as visual cues. The candidate does not need to match the reference orientation exactly, but it should be roughly aligned; modest tilt, perspective, or hand rotation is fine, but sideways or upside-down candidates are not. Judge only whether the visible candidate matches; do not decide based on whether the hands appear to be folding or manipulating it. Hands near the paper, lightly touching a peripheral edge, or covering a small irrelevant peripheral area do not by themselves require false. Return exactly false if hands cover a substantial portion of the paper's interior, cover its central region or any relevant fold or crease, or otherwise prevent confident verification of the complete shape and relevant folds. To return true, the entire paper outline, including every edge, corner, and tip, must be visible enough to verify. If the paper touches or crosses a camera-frame boundary, or is so close to one that its full boundary cannot be confirmed, return exactly false. Never infer off-frame or substantially hidden paper geometry from the visible portion. Also return exactly false if the candidate is missing, too blurry, or too obstructed to confidently verify the complete shape and relevant folds. When visibility is uncertain, return exactly false. Return exactly true only when the selected candidate matches the reference shape and is consistent with the criteria; otherwise return exactly false. Do not include any other text."
FOLD_CHECK_CRITERIA_PREFIX = "Criteria: "

FOLD_CHECK_CHAT_MAX_COMPLETION_TOKENS = 4


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
        "max_completion_tokens": FOLD_CHECK_CHAT_MAX_COMPLETION_TOKENS,
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
