from __future__ import annotations

from typing import Any

FOLD_CHECK_REFERENCE_IMAGE_LAYOUT = """\
- Top: The reference shape.
- Bottom: A camera frame that may contain the candidate paper model.
"""

FOLD_CHECK_NEGATIVE_EXEMPLAR_IMAGE_LAYOUT = """\
- Top left, labeled `TARGET SHAPE`: The shape the candidate must match.
- Top right, labeled `NOT TARGET`: A visually similar but incorrect shape that must be rejected.
- Bottom: A camera frame that may contain the candidate paper model.
"""

FOLD_CHECK_SYSTEM_PROMPT = f"""\
# Goal

Determine whether the candidate origami model in the provided composite image matches the reference shape.

# Image Layout

{FOLD_CHECK_REFERENCE_IMAGE_LAYOUT}
# Candidate Selection

- Evaluate only a candidate that is either resting on a surface or being held in a hand.
- If multiple candidates are visible, evaluate the largest one near the center of the camera frame.

# Comparison Rules

- Compare the selected candidate primarily against the reference shape, using the supplied criteria as visual cues.
- Different paper colors are acceptable, including a different color on each side.
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

FOLD_CHECK_NEGATIVE_EXEMPLAR_SYSTEM_PROMPT = f"""\
# Goal

Determine whether the candidate origami model in the provided composite image matches the target shape. Use the negative exemplar to resolve the specific visual distinction described by the supplied criteria.

# Image Layout

{FOLD_CHECK_NEGATIVE_EXEMPLAR_IMAGE_LAYOUT}
# Candidate Selection

- Evaluate only a candidate that is either resting on a surface or being held in a hand.
- If multiple candidates are visible, evaluate the largest one near the center of the camera frame.

# Comparison Rules

- Compare the selected candidate primarily against `TARGET SHAPE`, using the supplied criteria as visual cues.
- Use `NOT TARGET` only to understand the target-defining difference described by the supplied criteria. The target and negative exemplar may intentionally share most of their overall shape.
- Do not return false merely because the candidate resembles the negative exemplar overall. Compare the specific distinguishing feature instead.
- Return false if that target-defining feature is absent or the corresponding candidate feature matches `NOT TARGET` instead.
- Exact paper colors are irrelevant. Different paper colors are acceptable, including a different color on each side.
- Minor asymmetry is acceptable when the required shape, edges, folds, and layer relationships remain present.
- The candidate does not need to match the target orientation exactly, but its orientation should roughly match the target. Modest variations in tilt, perspective, or rotation are acceptable.
- Interpret positional terms in the supplied criteria, such as top, bottom, left, and right, relative to the candidate's own orientation.
- Base the decision only on whether the visible candidate matches the target, using the negative exemplar as a contrast for the specified distinguishing feature.

# Visibility Requirements

Return false if any of the following applies:

- Hands substantially cover the paper, including while folding or pressing it. Nearby hands or light contact are acceptable when the candidate's overall shape and required features remain clear.
- A feature needed to determine whether the candidate matches the target—such as an edge, corner, tip, fold, or crease—is not clearly visible.
- Any part of the candidate extends beyond the camera frame.
- No candidate is visible, or the candidate is too blurry.

Never infer the shape of substantially hidden parts of the paper from the visible portion.

When uncertain, return false.

# Output

- Return exactly one word: `true` or `false`. Do not include any other text.
- Return true only if the selected candidate meets visibility requirements, matches `TARGET SHAPE`, and is consistent with the supplied criteria and its target-defining contrast with `NOT TARGET`.
- Otherwise, return false.
"""

FOLD_CHECK_CRITERIA_PREFIX = "# Evaluation Criteria\n\n"


def fold_check_completion_payload(
    *,
    model: str,
    prompt: str,
    image_url: str,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Build an independent fold-check request without a prompt-cache thread."""
    return {
        "model": model,
        "max_completion_tokens": 4,
        "messages": [
            {
                "role": "system",
                "content": system_prompt or FOLD_CHECK_SYSTEM_PROMPT,
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
        ],
    }


def fold_check_criteria_text(prompt: str) -> str:
    return f"{FOLD_CHECK_CRITERIA_PREFIX}{prompt}"


def fold_check_system_prompt(*, has_negative_exemplar: bool) -> str:
    return (
        FOLD_CHECK_NEGATIVE_EXEMPLAR_SYSTEM_PROMPT
        if has_negative_exemplar
        else FOLD_CHECK_SYSTEM_PROMPT
    )


def fold_check_image_layout_description(*, has_negative_exemplar: bool) -> str:
    return (
        FOLD_CHECK_NEGATIVE_EXEMPLAR_IMAGE_LAYOUT
        if has_negative_exemplar
        else FOLD_CHECK_REFERENCE_IMAGE_LAYOUT
    )
