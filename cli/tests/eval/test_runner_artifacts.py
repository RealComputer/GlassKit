from __future__ import annotations

import os

import pytest

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


@pytest.mark.parametrize(
    ("target_id", "windows"),
    [
        ("?" + "😀" * 56, False),
        ("😀" * 120, True),
    ],
)
def test_failure_artifact_stem_bounds_multibyte_filesystem_units(
    target_id: str, windows: bool
) -> None:
    stem = _failure_artifact_stem(_result(target_id), windows=windows)
    filename = f"{stem}.json"
    units = (
        len(filename.encode("utf-16-le")) // 2
        if windows
        else len(os.fsencode(filename))
    )

    assert units <= 255
    assert stem.endswith("_00002_1.250s")


def test_failure_artifact_stem_with_multibyte_id_can_be_written(tmp_path) -> None:
    stem = _failure_artifact_stem(_result("?" + "😀" * 56), windows=False)
    path = tmp_path / f"{stem}.json"

    path.write_text("{}", encoding="utf-8")

    assert path.read_text(encoding="utf-8") == "{}"


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
