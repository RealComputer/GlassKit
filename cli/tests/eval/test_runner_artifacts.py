from __future__ import annotations

from glasskit.eval.models import SampleResult
from glasskit.eval.runner import _failure_artifact_stem


def test_failure_artifact_stem_is_windows_safe_and_collision_resistant() -> None:
    first = _failure_artifact_stem(_result(r"step:one\part?"))
    second = _failure_artifact_stem(_result(r"step?one\part:"))

    assert not set('<>:"/\\|?*').intersection(first)
    assert first != second
    assert first.endswith("_00002_1.250s")


def test_failure_artifact_stem_bounds_long_target_ids() -> None:
    stem = _failure_artifact_stem(_result("target" * 100))

    assert len(stem) <= 181
    assert stem.endswith("_00002_1.250s")


def _result(target_id: str) -> SampleResult:
    return SampleResult(
        case_name="case",
        target_id=target_id,
        target_label=None,
        sample_index=2,
        timestamp_s=1.25,
        status="failed",
        expected=True,
        observed=False,
        observed_value=False,
        compare_mode="exact",
        field=None,
        reason="mismatch",
        source="case.yaml",
    )
