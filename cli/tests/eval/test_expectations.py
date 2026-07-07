from __future__ import annotations

from pathlib import Path

import pytest

from glasskit.eval.expectations import load_eval_suite
from glasskit.eval.models import EvalConfigError


def test_range_expansion_uses_half_open_boundaries(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        sampling:
          every_s: 0.5
        targets:
          step_1:
            samples:
              - range: [0.0, 1.0]
                expect: false
              - range: [1.0, 2.0]
                every_s: 1.0
                expect: true
        """,
    )

    suite = load_eval_suite(eval_dir)

    samples = suite.cases[0].samples
    assert [sample.timestamp_s for sample in samples] == [0.0, 0.5, 1.0]
    assert [sample.expected for sample in samples] == [False, False, True]


def test_sparse_at_samples_expand_and_sort(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_3:
            samples:
              - at: [3.0, 1.0, 2.0]
                expect: true
              - at: 4.0
                expect: false
        """,
    )

    suite = load_eval_suite(eval_dir)

    assert [sample.timestamp_s for sample in suite.cases[0].samples] == [
        1.0,
        2.0,
        3.0,
        4.0,
    ]


def test_unlabeled_gaps_are_allowed(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, 1.0]
                expect: false
              - range: [5.0, 6.0]
                expect: true
        """,
    )

    suite = load_eval_suite(eval_dir)

    assert [sample.timestamp_s for sample in suite.cases[0].samples] == [
        0.0,
        0.5,
        5.0,
        5.5,
    ]


def test_overlapping_ranges_are_invalid(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, 1.0]
                expect: false
              - range: [0.5, 2.0]
                expect: true
        """,
    )

    with pytest.raises(EvalConfigError, match="overlaps"):
        load_eval_suite(eval_dir)


def test_point_inside_range_is_invalid(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, 1.0]
                expect: false
              - at: 0.5
                expect: true
        """,
    )

    with pytest.raises(EvalConfigError, match="overlaps"):
        load_eval_suite(eval_dir)


def test_schema_errors_include_nested_location(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        sampling:
          every_s: false
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: false
        """,
    )

    with pytest.raises(EvalConfigError, match=r"sampling\.every_s"):
        load_eval_suite(eval_dir)


@pytest.mark.parametrize(
    "sample_yaml",
    [
        """
              - at: .nan
                expect: true
        """,
        """
              - range: [0.0, .inf]
                expect: true
        """,
    ],
)
def test_non_finite_sample_times_are_invalid(tmp_path: Path, sample_yaml: str) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        f"""
        video: video.mp4
        targets:
          step_1:
            samples:
{sample_yaml}
        """,
    )

    with pytest.raises(EvalConfigError, match="finite"):
        load_eval_suite(eval_dir)


def test_unsupported_compare_mode_is_invalid(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: true
                compare:
                  mode: typo_mode
        """,
    )

    with pytest.raises(EvalConfigError, match="unsupported compare mode"):
        load_eval_suite(eval_dir)


def test_non_json_expected_value_is_invalid(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: 2026-01-01
        """,
    )

    with pytest.raises(EvalConfigError, match="JSON-like"):
        load_eval_suite(eval_dir)


def test_video_field_is_required(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: true
        """,
    )

    with pytest.raises(EvalConfigError, match="video"):
        load_eval_suite(eval_dir)


def test_config_yaml_loads_eval_thresholds(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: true
        """,
    )
    (eval_dir / "config.yaml").write_text(
        """
        thresholds:
          min_pass_rate: 0.9
          max_failures: 2
          per_target:
            step_1:
              min_pass_rate: 0.95
        """,
        encoding="utf-8",
    )

    suite = load_eval_suite(eval_dir)

    assert suite.thresholds.min_pass_rate == 0.9
    assert suite.thresholds.max_failures == 2
    assert suite.thresholds.per_target["step_1"].min_pass_rate == 0.95


def _eval_dir(tmp_path: Path, case_yaml: str) -> Path:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "video.mp4").write_bytes(b"placeholder")
    (cases_dir / "case-001.yaml").write_text(case_yaml, encoding="utf-8")
    return eval_dir
