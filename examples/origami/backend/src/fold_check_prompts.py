from __future__ import annotations

from typing import Any

FOLD_CHECK_SYSTEM_PROMPT = """\
# Goal

Determine whether the candidate origami model in the provided composite image matches the reference shape.

# Image Layout

- Top: The reference shape.
- Bottom: A camera frame that may contain the candidate paper model.

# Candidate Selection

- Evaluate only a candidate that is either resting on a surface or being held in a hand.
- If multiple candidates are visible, evaluate the largest one near the center of the camera frame.

# Comparison Rules

- Compare the selected candidate primarily against the reference shape, using the supplied criteria as visual cues.
- The candidate does not need to match the reference orientation exactly, but its orientation should roughly match the reference. Modest variations in tilt, perspective, or rotation are acceptable.
- Base the decision only on whether the visible candidate matches the reference.

# Visibility Requirements

Return false if any of the following applies:

- Hands substantially cover the paper, including while folding or pressing it. Nearby hands or light contact are acceptable when the candidate's overall shape and required features remain clear.
- A feature needed to determine whether the candidate matches the reference—such as an edge, corner, tip, fold, or crease—is not clearly visible.
- Any part of the candidate extends beyond the camera frame.
- No candidate is visible, or the candidate is too blurry.

Never infer the shape of substantially hidden parts of the paper from the visible portion.

When uncertain, return false.

# Output

- Return exactly one word: `true` or `false`. Do not include any other text.
- Return true only if the selected candidate meets visibility requirements, matches the reference shape, and is consistent with the supplied criteria.
- Otherwise, return false.
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
