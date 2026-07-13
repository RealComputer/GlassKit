from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from google import genai
from PIL import Image

from eval.generate_case import (
    BACKEND_DIR,
    GEMINI_IMAGE_RESOLUTION,
    GEMINI_MODEL,
    GEMINI_SERVICE_TIER,
    _decode_sample_images,
    _jpeg_base64,
    _time_key,
)
from src.fold_check import load_fold_check_reference_images, load_fold_check_steps
from src.fold_check_prompts import FOLD_CHECK_SYSTEM_PROMPT
from src.origami_config import OrigamiStep

GEMINI_THINKING_LEVEL = "high"
DEFAULT_EXAMPLES_PER_CLASS = 10
TIME_EPSILON = 1e-9

AUTHOR_SYSTEM_INSTRUCTION = """\
You are a visual specification writer for an origami fold classifier. Analyze the reference drawings and labeled camera examples carefully, then write concise, observable criteria that distinguish the target fold from nearby fold states in new, unseen recordings.

The target reference drawing is authoritative. Labeled examples only clarify how its geometry and layer topology can appear in camera images. Infer reusable shape, edge, crease, overlap, and layer relationships. Never turn incidental details from the examples into requirements.
"""

AUTHOR_REQUEST = """\
# Task

Write improved step-specific evaluation criteria for {target_id} ({target_title}). The fast evaluator will receive the frozen system prompt below, your criteria, and a composite image with the target reference above a camera frame.

# Frozen Evaluator System Prompt

{system_prompt}

# Current Step Criteria

{current_criteria}

# Evidence Rules

- The target reference drawing is the source of truth for the intended fold.
- Positive examples are reviewed frames where the target fold is complete. Negative examples are reviewed frames where it is not complete.
- When fast-evaluator feedback is attached to an example, the reviewed label remains ground truth. Use the mismatch to make general visual distinctions easier for a smaller model; do not write a rule for that individual image.
- Use the examples to understand stable geometry and layer topology, especially confusing adjacent states. Do not merely summarize or memorize them.
- Generalize to different people, paper sizes, two-sided paper colors, lighting, surfaces, cameras, modest rotations, and perspective.
- Do not mention example identifiers, timestamps, exact colors, the recording background, or the order in which examples appear.
- Do not require a feature just because it happens to be visible in every positive example unless the reference or fold topology supports it.
- Do not weaken a requirement just because one negative example superficially resembles the target.
- Prefer the smallest set of independently visible, discriminative features. Avoid duplicating generic visibility rules already present in the frozen system prompt.
- Describe visible evidence only. Do not ask the evaluator to infer hidden paper layers or folding actions.

# Required Response

Return one JSON object with exactly these fields:

- `visual_analysis`: a clear explanation of the target's defining geometry and layer relationships, including how it differs from the most confusable negative states.
- `generalization_notes`: a JSON array explaining why the proposed rules should transfer beyond these examples.
- `criteria`: Markdown containing `## Required Features`, `## Acceptable Variations`, and `## Reject If`. Keep it under 220 words and ready to store directly in `origami_steps.json`.
"""

_FORBIDDEN_CRITERIA_PATTERNS = (
    (
        re.compile(r"\b(?:positive|negative)\s+example\b|\b[PN]\d+\b", re.I),
        "example identifiers",
    ),
    (
        re.compile(r"\b\d+(?:\.\d+)?\s*(?:s|sec|secs|second|seconds)\b", re.I),
        "timestamps",
    ),
    (
        re.compile(
            r"\b(?:black|blue|brown|cyan|gray|green|grey|magenta|orange|pink|purple|red|white|yellow)\b",
            re.I,
        ),
        "exact colors",
    ),
    (
        re.compile(
            r"\b(?:carpet|chair|chairs|classroom|table|tray|wood|wooden)\b",
            re.I,
        ),
        "recording background objects",
    ),
)


@dataclass(frozen=True)
class CaseExample:
    timestamp_s: float
    expected: bool
    block_index: int


@dataclass(frozen=True)
class LoadedCase:
    path: Path
    video_path: Path
    target_id: str
    examples: list[CaseExample]


@dataclass(frozen=True)
class CriteriaSuggestion:
    visual_analysis: str
    generalization_notes: list[str]
    criteria: str


@dataclass(frozen=True)
class EvalObservation:
    timestamp_s: float
    expected: bool
    observed: bool
    status: str


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = _suggest_criteria(
            case_path=args.case.expanduser().resolve(),
            target_id=args.target,
            steps_path=args.steps.expanduser().resolve(),
            examples_per_class=args.examples_per_class,
            eval_results_path=(
                args.eval_results.expanduser().resolve()
                if args.eval_results is not None
                else None
            ),
        )
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.output is None:
            print(rendered, end="")
        else:
            output_path = args.output.expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            print(f"wrote {output_path}", flush=True)
            print(result["criteria"], flush=True)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr, flush=True)
        return 130
    except Exception as error:
        print(f"error: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            f"Ask {GEMINI_MODEL} to propose generalizable fold criteria from a "
            "reference and reviewed eval frames."
        )
    )
    parser.add_argument(
        "--case",
        required=True,
        type=Path,
        help="Reviewed eval case YAML containing the target's labeled samples.",
    )
    parser.add_argument("--target", required=True, help="Origami step id, e.g. step_5.")
    parser.add_argument(
        "--steps",
        type=Path,
        default=BACKEND_DIR / "assets" / "origami_steps.json",
        help="Origami steps JSON. Defaults to the backend's active step config.",
    )
    parser.add_argument(
        "--examples-per-class",
        type=_positive_int_arg,
        default=DEFAULT_EXAMPLES_PER_CLASS,
        help=(
            "Maximum reviewed frames to include for each expected value. Samples "
            f"are spread across label blocks. Defaults to {DEFAULT_EXAMPLES_PER_CLASS}."
        ),
    )
    parser.add_argument(
        "--eval-results",
        type=Path,
        help=(
            "Optional glasskit eval --output-json report. Selected examples are "
            "annotated with fast-evaluator matches and mismatches."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path. Without it, the report is printed.",
    )
    return parser.parse_args(argv)


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _suggest_criteria(
    *,
    case_path: Path,
    target_id: str,
    steps_path: Path,
    examples_per_class: int,
    eval_results_path: Path | None,
) -> dict[str, Any]:
    steps = load_fold_check_steps(steps_path)
    step_index = next(
        (index for index, step in enumerate(steps) if step.id == target_id),
        None,
    )
    if step_index is None:
        raise RuntimeError(f"unknown origami target id: {target_id}")
    step = steps[step_index]
    loaded_case = _load_case(case_path, target_id=target_id)
    observations = (
        _load_eval_observations(
            eval_results_path,
            case_name=case_path.stem,
            target_id=target_id,
        )
        if eval_results_path is not None
        else None
    )
    selected = _select_examples(
        loaded_case.examples,
        per_class=examples_per_class,
        observations=observations,
    )
    selected_values = {example.expected for example in selected}
    if selected_values != {False, True}:
        raise RuntimeError(
            "criteria authoring requires reviewed true and false samples"
        )

    images_by_time = dict(
        _decode_sample_images(
            loaded_case.video_path,
            [example.timestamp_s for example in selected],
        )
    )
    references = load_fold_check_reference_images(steps)
    inputs = _build_authoring_inputs(
        step=step,
        step_index=step_index,
        steps=steps,
        references=references,
        selected=selected,
        images_by_time=images_by_time,
        observations=observations,
    )
    suggestion, interaction_id = _call_gemini(inputs, target_id=target_id)
    return {
        "target_id": target_id,
        "case": str(loaded_case.path),
        "model": GEMINI_MODEL,
        "thinking_level": GEMINI_THINKING_LEVEL,
        "interaction_id": interaction_id,
        "selected_examples": {
            "false": [
                example.timestamp_s for example in selected if not example.expected
            ],
            "true": [example.timestamp_s for example in selected if example.expected],
        },
        "eval_results": str(eval_results_path)
        if eval_results_path is not None
        else None,
        "evaluator_feedback": (
            [
                {
                    "timestamp_s": example.timestamp_s,
                    "expected": observation.expected,
                    "observed": observation.observed,
                    "status": observation.status,
                }
                for example in selected
                if observations is not None
                and (observation := observations.get(_time_key(example.timestamp_s)))
                is not None
            ]
            if observations is not None
            else None
        ),
        "visual_analysis": suggestion.visual_analysis,
        "generalization_notes": suggestion.generalization_notes,
        "criteria": suggestion.criteria,
    }


def _load_case(path: Path, *, target_id: str) -> LoadedCase:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("case YAML must be an object")
    video_raw = raw.get("video")
    if not isinstance(video_raw, str) or not video_raw.strip():
        raise RuntimeError("case video must be a non-empty path")
    video_path = (path.parent / video_raw).resolve()
    if not video_path.is_file():
        raise RuntimeError(f"case video not found: {video_path}")

    every_s = 0.5
    sampling = raw.get("sampling")
    if sampling is not None:
        if not isinstance(sampling, dict):
            raise RuntimeError("case sampling must be an object")
        every_s = _positive_number(sampling.get("every_s", every_s), "sampling.every_s")

    targets = raw.get("targets")
    if not isinstance(targets, dict):
        raise RuntimeError("case targets must be an object")
    raw_target = targets.get(target_id)
    if not isinstance(raw_target, dict):
        raise RuntimeError(f"target not found in case: {target_id}")
    raw_samples = raw_target.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise RuntimeError(f"target {target_id} must contain samples")

    examples: list[CaseExample] = []
    for block_index, raw_block in enumerate(raw_samples, start=1):
        examples.extend(
            _expand_case_block(
                raw_block,
                block_index=block_index,
                default_every_s=every_s,
            )
        )
    if not examples:
        raise RuntimeError(f"target {target_id} contains no non-ignored samples")
    return LoadedCase(
        path=path,
        video_path=video_path,
        target_id=target_id,
        examples=examples,
    )


def _expand_case_block(
    raw: Any,
    *,
    block_index: int,
    default_every_s: float,
) -> list[CaseExample]:
    label = f"sample block {block_index}"
    if not isinstance(raw, dict):
        raise RuntimeError(f"{label} must be an object")
    expected = raw.get("expect")
    if not isinstance(expected, bool):
        raise RuntimeError(f"{label} expect must be true or false")
    if raw.get("ignore") is not None:
        return []

    has_at = raw.get("at") is not None
    has_range = raw.get("range") is not None
    if has_at == has_range:
        raise RuntimeError(f"{label} must contain exactly one of at or range")

    if has_at:
        raw_at = raw["at"]
        values = raw_at if isinstance(raw_at, list) else [raw_at]
        if not values:
            raise RuntimeError(f"{label} at must not be empty")
        timestamps = [_nonnegative_number(value, f"{label} at") for value in values]
    else:
        raw_range = raw["range"]
        if not isinstance(raw_range, list | tuple) or len(raw_range) != 2:
            raise RuntimeError(f"{label} range must be [start, end]")
        start_s = _nonnegative_number(raw_range[0], f"{label} range start")
        end_s = _nonnegative_number(raw_range[1], f"{label} range end")
        if end_s <= start_s:
            raise RuntimeError(f"{label} range end must be greater than start")
        every_s = _positive_number(raw.get("every_s", default_every_s), "every_s")
        timestamps = []
        timestamp_s = start_s
        while timestamp_s < end_s - TIME_EPSILON:
            timestamps.append(round(timestamp_s, 9))
            timestamp_s += every_s

    return [
        CaseExample(
            timestamp_s=timestamp_s,
            expected=expected,
            block_index=block_index,
        )
        for timestamp_s in timestamps
    ]


def _load_eval_observations(
    path: Path,
    *,
    case_name: str,
    target_id: str,
) -> dict[str, EvalObservation]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
        raise RuntimeError("eval results JSON must contain a results array")
    observations: dict[str, EvalObservation] = {}
    for raw_result in raw["results"]:
        if not isinstance(raw_result, dict):
            raise RuntimeError("eval results entries must be objects")
        if raw_result.get("case") != case_name or raw_result.get("target") != target_id:
            continue
        expected = raw_result.get("expected")
        observed = raw_result.get("observed_value")
        if not isinstance(expected, bool) or not isinstance(observed, bool):
            continue
        timestamp_s = _nonnegative_number(
            raw_result.get("timestamp_s"),
            "eval result timestamp_s",
        )
        status = raw_result.get("status")
        if not isinstance(status, str) or not status.strip():
            raise RuntimeError("eval result status must be a non-empty string")
        key = _time_key(timestamp_s)
        if key in observations:
            raise RuntimeError(
                f"duplicate eval result for {target_id} at {timestamp_s:g}s"
            )
        observations[key] = EvalObservation(
            timestamp_s=timestamp_s,
            expected=expected,
            observed=observed,
            status=status.strip(),
        )
    if not observations:
        raise RuntimeError(
            f"eval results contain no scored samples for {case_name}/{target_id}"
        )
    return observations


def _select_examples(
    examples: list[CaseExample],
    *,
    per_class: int,
    observations: dict[str, EvalObservation] | None = None,
) -> list[CaseExample]:
    selected: list[CaseExample] = []
    for expected in (False, True):
        class_examples = [
            example for example in examples if example.expected is expected
        ]
        if not class_examples:
            continue
        class_selected: list[CaseExample] = []
        if observations is not None:
            misclassified = [
                example
                for example in class_examples
                if (observation := observations.get(_time_key(example.timestamp_s)))
                is not None
                and observation.expected is expected
                and observation.observed is not expected
            ]
            class_selected.extend(
                _sample_groups(
                    _group_examples(misclassified),
                    limit=min(per_class, len(misclassified)),
                )
            )

        remaining = per_class - len(class_selected)
        if remaining > 0:
            already_selected = set(class_selected)
            candidates = [
                example for example in class_examples if example not in already_selected
            ]
            class_selected.extend(
                _sample_groups(
                    _group_examples(candidates),
                    limit=min(remaining, len(candidates)),
                )
            )
        selected.extend(class_selected)
    return sorted(selected, key=lambda example: (example.expected, example.timestamp_s))


def _group_examples(
    examples: list[CaseExample],
) -> dict[int, list[CaseExample]]:
    groups: dict[int, list[CaseExample]] = defaultdict(list)
    for example in examples:
        groups[example.block_index].append(example)
    return groups


def _sample_groups(
    groups: dict[int, list[CaseExample]],
    *,
    limit: int,
) -> list[CaseExample]:
    ordered_groups = [groups[index] for index in sorted(groups)]
    total = sum(len(group) for group in ordered_groups)
    limit = min(limit, total)
    if limit == total:
        return [example for group in ordered_groups for example in group]

    if limit < len(ordered_groups):
        ranked = sorted(
            enumerate(ordered_groups),
            key=lambda item: (-len(item[1]), item[0]),
        )[:limit]
        chosen_groups = [group for _, group in sorted(ranked)]
        quotas = [1] * len(chosen_groups)
    else:
        chosen_groups = ordered_groups
        quotas = [1] * len(chosen_groups)
        for _ in range(limit - len(chosen_groups)):
            candidates = [
                index
                for index, (group, quota) in enumerate(
                    zip(chosen_groups, quotas, strict=True)
                )
                if quota < len(group)
            ]
            best = max(
                candidates,
                key=lambda index: (
                    len(chosen_groups[index]) / (quotas[index] + 1),
                    -index,
                ),
            )
            quotas[best] += 1

    return [
        group[index]
        for group, quota in zip(chosen_groups, quotas, strict=True)
        for index in _even_indices(len(group), quota)
    ]


def _even_indices(length: int, count: int) -> list[int]:
    if count == 1:
        return [(length - 1) // 2]
    return [round(index * (length - 1) / (count - 1)) for index in range(count)]


def _build_authoring_inputs(
    *,
    step: OrigamiStep,
    step_index: int,
    steps: list[OrigamiStep],
    references: dict[str, Image.Image],
    selected: list[CaseExample],
    images_by_time: dict[str, Image.Image],
    observations: dict[str, EvalObservation] | None,
) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": AUTHOR_REQUEST.format(
                target_id=step.id,
                target_title=step.title,
                system_prompt=FOLD_CHECK_SYSTEM_PROMPT,
                current_criteria=step.criteria,
            ),
        },
        {"type": "text", "text": "Authoritative TARGET reference drawing:"},
        _image_input(references[step.id]),
    ]
    if step_index > 0:
        previous = steps[step_index - 1]
        inputs.extend(
            [
                {
                    "type": "text",
                    "text": "NON-TARGET preceding-step reference drawing:",
                },
                _image_input(references[previous.id]),
            ]
        )
    if step_index + 1 < len(steps):
        following = steps[step_index + 1]
        inputs.extend(
            [
                {
                    "type": "text",
                    "text": "NON-TARGET following-step reference drawing:",
                },
                _image_input(references[following.id]),
            ]
        )

    counts = {False: 0, True: 0}
    for example in selected:
        counts[example.expected] += 1
        prefix = "P" if example.expected else "N"
        label = "POSITIVE" if example.expected else "NEGATIVE"
        image = images_by_time.get(_time_key(example.timestamp_s))
        if image is None:
            raise RuntimeError(f"video decoder missed a selected {label.lower()} frame")
        feedback = ""
        if observations is not None:
            observation = observations.get(_time_key(example.timestamp_s))
            if observation is None:
                raise RuntimeError("eval results are missing a selected camera example")
            if observation.expected is not example.expected:
                raise RuntimeError("eval result disagrees with the reviewed case label")
            verdict = (
                "MATCHED"
                if observation.observed is example.expected
                else "MISCLASSIFIED"
            )
            feedback = (
                f" Fast evaluator returned {str(observation.observed).upper()} "
                f"({verdict})."
            )
        inputs.extend(
            [
                {
                    "type": "text",
                    "text": (
                        f"Reviewed {label} camera example "
                        f"{prefix}{counts[example.expected]}.{feedback}"
                    ),
                },
                _image_input(image),
            ]
        )
    return inputs


def _image_input(image: Image.Image) -> dict[str, Any]:
    return {
        "type": "image",
        "data": _jpeg_base64(image),
        "mime_type": "image/jpeg",
        "resolution": GEMINI_IMAGE_RESOLUTION,
    }


def _call_gemini(
    inputs: list[dict[str, Any]],
    *,
    target_id: str,
) -> tuple[CriteriaSuggestion, str | None]:
    client = genai.Client()
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            interaction = client.interactions.create(
                model=GEMINI_MODEL,
                system_instruction=AUTHOR_SYSTEM_INSTRUCTION,
                input=inputs,
                generation_config={"thinking_level": GEMINI_THINKING_LEVEL},
                service_tier=GEMINI_SERVICE_TIER,
                store=False,
            )
            response_text = str(getattr(interaction, "output_text", "") or "").strip()
            suggestion = _parse_suggestion(response_text)
            interaction_id = cast("str | None", getattr(interaction, "id", None))
            return suggestion, interaction_id
        except Exception as error:
            last_error = error
            if attempt == 3:
                break
            delay_s = 5 * (2 ** (attempt - 1))
            print(
                f"Gemini criteria call failed for {target_id}; retrying in "
                f"{delay_s}s: {error}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay_s)
    raise RuntimeError(f"Gemini criteria call failed for {target_id}: {last_error}")


def _parse_suggestion(response_text: str) -> CriteriaSuggestion:
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Gemini returned invalid JSON: {response_text!r}"
        ) from error
    if not isinstance(raw, dict):
        raise RuntimeError("Gemini criteria response must be a JSON object")
    if set(raw) != {"visual_analysis", "generalization_notes", "criteria"}:
        raise RuntimeError("Gemini criteria response has unexpected fields")

    visual_analysis = _nonempty_string(raw["visual_analysis"], "visual_analysis")
    criteria = _nonempty_string(raw["criteria"], "criteria")
    notes_raw = raw["generalization_notes"]
    if not isinstance(notes_raw, list) or not notes_raw:
        raise RuntimeError("generalization_notes must be a non-empty array")
    notes = [_nonempty_string(note, "generalization_notes item") for note in notes_raw]
    for section in (
        "## Required Features",
        "## Acceptable Variations",
        "## Reject If",
    ):
        if section not in criteria:
            raise RuntimeError(f"criteria is missing {section}")
    if len(criteria.split()) > 220:
        raise RuntimeError("criteria exceeds the 220-word limit")
    for pattern, label in _FORBIDDEN_CRITERIA_PATTERNS:
        if pattern.search(criteria):
            raise RuntimeError(f"criteria contains video-specific {label}")
    return CriteriaSuggestion(
        visual_analysis=visual_analysis,
        generalization_notes=notes,
        criteria=criteria,
    )


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} must be a non-empty string")
    return value.strip()


def _positive_number(value: Any, label: str) -> float:
    parsed = _finite_number(value, label)
    if parsed <= 0:
        raise RuntimeError(f"{label} must be greater than zero")
    return parsed


def _nonnegative_number(value: Any, label: str) -> float:
    parsed = _finite_number(value, label)
    if parsed < 0:
        raise RuntimeError(f"{label} must not be negative")
    return parsed


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RuntimeError(f"{label} must be a number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RuntimeError(f"{label} must be finite")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
