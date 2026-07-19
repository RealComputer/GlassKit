from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .models import SUPPORTED_COMPARE_MODES, CompareOutcome, SampleExpectation


def compare_observation(observation: Any, sample: SampleExpectation) -> CompareOutcome:
    observed_value, field_error = _extract_field(observation, sample.field)
    mode = _comparison_mode(sample)
    if field_error is not None:
        return CompareOutcome(False, field_error, None, mode)
    if observation is None and sample.expected is not None:
        return CompareOutcome(
            False,
            "adapter returned null but the sample expects a non-null value",
            None,
            mode,
        )
    if mode not in SUPPORTED_COMPARE_MODES:
        return CompareOutcome(
            False, f"unsupported compare mode: {mode}", observed_value, mode
        )

    if mode == "exact":
        passed = _exact_equal(observed_value, sample.expected)
        return CompareOutcome(
            passed,
            "matched" if passed else "expected exact match",
            observed_value,
            mode,
        )

    if mode == "numeric":
        return _compare_numeric(
            observed_value, sample.expected, sample.compare.tolerance
        )

    if mode == "json_subset":
        passed = _json_subset(sample.expected, observed_value)
        return CompareOutcome(
            passed,
            "matched" if passed else "expected JSON subset",
            observed_value,
            mode,
        )

    return _compare_set(mode, observed_value, sample.expected)


def _comparison_mode(sample: SampleExpectation) -> str:
    if sample.compare.mode:
        return sample.compare.mode
    expected = sample.expected
    if isinstance(expected, bool | str) or expected is None:
        return "exact"
    if _is_number(expected):
        return "numeric"
    return "exact"


def _extract_field(observation: Any, field: str | None) -> tuple[Any, str | None]:
    if not field:
        return observation, None
    current = observation
    for part in field.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return None, _missing_field_reason(field)
            current = current[part]
            continue
        if isinstance(current, Sequence) and not isinstance(current, str | bytes):
            if not part.isdecimal():
                return None, _missing_field_reason(field)
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None, _missing_field_reason(field)
            continue
        return None, _missing_field_reason(field)
    return current, None


def _missing_field_reason(field: str) -> str:
    return f"adapter observation is missing configured field: {field}"


def _compare_numeric(
    observed: Any, expected: Any, tolerance: float | None
) -> CompareOutcome:
    if not _is_number(expected):
        return CompareOutcome(
            False,
            "numeric comparison expected value is not numeric",
            observed,
            "numeric",
        )
    if not _is_number(observed):
        return CompareOutcome(
            False, "observed value is not numeric", observed, "numeric"
        )
    tolerance = 0.0 if tolerance is None else tolerance
    difference = abs(float(observed) - float(expected))
    passed = difference <= tolerance
    return CompareOutcome(
        passed,
        "matched"
        if passed
        else f"numeric difference {difference:g} exceeds tolerance {tolerance:g}",
        observed,
        "numeric",
    )


def _compare_set(mode: str, observed: Any, expected: Any) -> CompareOutcome:
    observed_items = _sequence_items(observed)
    expected_items = _sequence_items(expected)
    if observed_items is None:
        return CompareOutcome(False, "observed value is not an array", observed, mode)
    if expected_items is None:
        return CompareOutcome(False, "expected value is not an array", observed, mode)

    observed_set = {_canonical_json(item) for item in observed_items}
    expected_set = {_canonical_json(item) for item in expected_items}
    if mode == "set_equals":
        passed = observed_set == expected_set
        reason = "matched" if passed else "expected set equality"
    elif mode == "set_contains_any":
        passed = bool(observed_set & expected_set)
        reason = "matched" if passed else "expected any matching set item"
    else:
        passed = expected_set <= observed_set
        reason = "matched" if passed else "expected all set items"
    return CompareOutcome(passed, reason, observed, mode)


def _exact_equal(observed: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(observed, bool):
        return (
            isinstance(expected, bool)
            and isinstance(observed, bool)
            and observed == expected
        )
    return observed == expected


def _json_subset(expected: Any, observed: Any) -> bool:
    if isinstance(expected, Mapping):
        if not isinstance(observed, Mapping):
            return False
        return all(
            key in observed and _json_subset(value, observed[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(observed, list):
            return False
        unmatched = list(observed)
        for expected_item in expected:
            match_index = next(
                (
                    index
                    for index, observed_item in enumerate(unmatched)
                    if _json_subset(expected_item, observed_item)
                ),
                None,
            )
            if match_index is None:
                return False
            unmatched.pop(match_index)
        return True
    return _exact_equal(observed, expected)


def _sequence_items(value: Any) -> list[Any] | None:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        return None
    return list(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
