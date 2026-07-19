from __future__ import annotations

from pathlib import Path

from glasskit.eval.compare import compare_observation
from glasskit.eval.models import ComparisonConfig, SampleExpectation


def test_exact_boolean_does_not_match_integer() -> None:
    sample = _sample(expected=True)

    outcome = compare_observation(1, sample)

    assert not outcome.passed


def test_numeric_tolerance() -> None:
    sample = _sample(
        expected=0.5, compare=ComparisonConfig(mode="numeric", tolerance=0.1)
    )

    outcome = compare_observation(
        {"level": 0.57}, _sample(expected=0.5, field="level", compare=sample.compare)
    )

    assert outcome.passed


def test_missing_field_fails_clearly() -> None:
    sample = _sample(expected=True, field="result.matches")

    outcome = compare_observation({"result": {}}, sample)

    assert not outcome.passed
    assert outcome.reason == (
        "adapter observation is missing configured field: result.matches"
    )


def test_null_observation_failure_explains_non_null_expectation() -> None:
    outcome = compare_observation(None, _sample(expected=True))

    assert not outcome.passed
    assert outcome.reason == (
        "adapter returned null but the sample expects a non-null value"
    )


def test_json_subset() -> None:
    sample = _sample(
        expected={"ingredients": ["orange juice"]},
        compare=ComparisonConfig(mode="json_subset"),
    )

    outcome = compare_observation(
        {"ingredients": ["orange juice", "lime"], "extra": True},
        sample,
    )

    assert outcome.passed


def test_set_contains_all() -> None:
    sample = _sample(
        expected=["rice", "nori"],
        field="detected_classes",
        compare=ComparisonConfig(mode="set_contains_all"),
    )

    outcome = compare_observation(
        {"detected_classes": ["nori", "rice", "fish"]}, sample
    )

    assert outcome.passed


def test_negative_list_indexes_are_missing_fields() -> None:
    sample = _sample(expected="last", field="items.-1")

    outcome = compare_observation({"items": ["first", "last"]}, sample)

    assert not outcome.passed
    assert outcome.reason == "adapter observation is missing configured field: items.-1"


def _sample(
    *,
    expected: object,
    field: str | None = None,
    compare: ComparisonConfig | None = None,
) -> SampleExpectation:
    return SampleExpectation(
        case_name="case",
        target_id="target",
        target_index=0,
        target_label=None,
        target_config={},
        video_path=Path("video.mp4"),
        timestamp_s=0.0,
        sample_index=0,
        expected=expected,
        field=field,
        compare=compare or ComparisonConfig(),
    )
