from __future__ import annotations

from typing import Any

FOLD_CHECK_SYSTEM_PROMPT = """\
# Origami Fold Verification

## Task

Determine whether a candidate origami model in a single composite image matches the reference shape.

## Image Layout

- **Top:** The reference shape.
- **Bottom:** A camera frame that may contain the candidate paper model.

## Candidate Selection

- Only judge a candidate that is resting on a surface or being held in a hand.
- If multiple candidates are visible, judge the largest candidate near the center of the camera frame.
- Ignore smaller, background, or off-center candidates.

## Comparison Rules

- Compare the selected candidate primarily with the reference shape. Use the supplied criteria as visual cues.
- The candidate does not need to match the reference orientation exactly, but it should be roughly aligned. Modest tilt, perspective, or hand rotation is acceptable, but sideways or upside-down candidates are not.
- Judge only whether the visible candidate matches. Do not decide based on whether the hands appear to be folding or manipulating it.
- Hands near the paper, lightly touching a peripheral edge, or covering a small, irrelevant peripheral area do not by themselves require `false`.

## Visibility Requirements

Return exactly `false` if any of the following is true:

- Hands cover a substantial portion of the paper's interior, its central region, or any relevant fold or crease, or otherwise prevent confident verification of the complete shape and relevant folds.
- The entire paper outline, including every edge, corner, and tip, is not visible enough to verify.
- The paper touches or crosses a camera-frame boundary, or is so close to one that its full boundary cannot be confirmed.
- The candidate is missing, too blurry, or too obstructed to confidently verify the complete shape and relevant folds.

Never infer off-frame or substantially hidden paper geometry from the visible portion.
When visibility is uncertain, return exactly `false`.

## Output

- Return exactly `true` only when the selected candidate matches the reference shape and is consistent with the supplied criteria.
- Otherwise, return exactly `false`.
- Do not include any other text.
"""
FOLD_CHECK_CRITERIA_PREFIX = "# Evaluation Criteria\n\n"

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
