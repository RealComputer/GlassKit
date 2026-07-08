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


def test_yml_case_files_are_discovered(tmp_path: Path) -> None:
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
        case_suffix=".yml",
    )

    suite = load_eval_suite(eval_dir)

    assert [case.name for case in suite.cases] == ["case-001"]


def test_case_filter_matches_yml_case_file(tmp_path: Path) -> None:
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
        case_suffix=".yml",
    )

    suite = load_eval_suite(eval_dir, case_filter="case-001")

    assert suite.cases[0].path.name == "case-001.yml"


def test_case_filter_accepts_yaml_filename(tmp_path: Path) -> None:
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

    suite = load_eval_suite(eval_dir, case_filter="case-001.yaml")

    assert suite.cases[0].name == "case-001"


def test_case_filter_accepts_yml_filename(tmp_path: Path) -> None:
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
        case_suffix=".yml",
    )

    suite = load_eval_suite(eval_dir, case_filter="case-001.yml")

    assert suite.cases[0].name == "case-001"


def test_target_filter_selects_only_matching_target(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: false
          step_2:
            samples:
              - at: [1.0, 2.0]
                expect: true
        """,
    )

    suite = load_eval_suite(eval_dir, case_filter="case-001", target_filter="step_2")

    case = suite.cases[0]
    assert [target.id for target in case.targets] == ["step_2"]
    assert [sample.target_id for sample in case.samples] == ["step_2", "step_2"]
    assert [sample.sample_index for sample in case.samples] == [1, 2]


def test_target_filter_without_case_keeps_matching_cases(tmp_path: Path) -> None:
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
    (eval_dir / "cases" / "case-002.yaml").write_text(
        """
        video: video.mp4
        targets:
          step_2:
            samples:
              - at: 1.0
                expect: true
        """,
        encoding="utf-8",
    )

    suite = load_eval_suite(eval_dir, target_filter="step_2")

    assert [case.name for case in suite.cases] == ["case-002"]
    assert [target.id for target in suite.cases[0].targets] == ["step_2"]


def test_target_filter_skips_non_matching_case_before_resolving_video(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: missing.mp4
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: true
        """,
    )
    (eval_dir / "cases" / "case-002.yaml").write_text(
        """
        video: video.mp4
        targets:
          step_2:
            samples:
              - at: 1.0
                expect: true
        """,
        encoding="utf-8",
    )

    suite = load_eval_suite(eval_dir, target_filter="step_2")

    assert [case.name for case in suite.cases] == ["case-002"]


def test_target_filter_errors_when_target_is_missing(tmp_path: Path) -> None:
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

    with pytest.raises(
        EvalConfigError, match="no eval targets found matching target 'step_2'"
    ):
        load_eval_suite(eval_dir, target_filter="step_2")


def test_target_filter_rejects_empty_target_id(tmp_path: Path) -> None:
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

    with pytest.raises(EvalConfigError, match="target must be a target id"):
        load_eval_suite(eval_dir, target_filter="")


def test_uppercase_yaml_case_suffix_is_ignored(tmp_path: Path) -> None:
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
        case_suffix=".YML",
    )

    with pytest.raises(EvalConfigError, match="no eval cases found"):
        load_eval_suite(eval_dir)


def test_duplicate_yaml_case_stems_are_invalid(tmp_path: Path) -> None:
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
    (eval_dir / "cases" / "case-001.yml").write_text(
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: true
        """,
        encoding="utf-8",
    )

    with pytest.raises(EvalConfigError, match="multiple eval case files"):
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


def test_config_yml_loads_eval_thresholds(tmp_path: Path) -> None:
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
    (eval_dir / "config.yml").write_text(
        """
        thresholds:
          min_pass_rate: 0.9
        """,
        encoding="utf-8",
    )

    suite = load_eval_suite(eval_dir)

    assert suite.thresholds.min_pass_rate == 0.9


def test_uppercase_yaml_config_suffix_is_ignored(tmp_path: Path) -> None:
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
    (eval_dir / "config.YML").write_text(
        """
        thresholds:
          min_pass_rate: 0.9
        """,
        encoding="utf-8",
    )

    suite = load_eval_suite(eval_dir)

    assert suite.thresholds.min_pass_rate is None


def test_duplicate_eval_config_files_are_invalid(tmp_path: Path) -> None:
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
    (eval_dir / "config.yaml").write_text("thresholds: {}\n", encoding="utf-8")
    (eval_dir / "config.yml").write_text("thresholds: {}\n", encoding="utf-8")

    with pytest.raises(EvalConfigError, match="multiple eval config files"):
        load_eval_suite(eval_dir)


def _eval_dir(tmp_path: Path, case_yaml: str, *, case_suffix: str = ".yaml") -> Path:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "video.mp4").write_bytes(b"placeholder")
    (cases_dir / f"case-001{case_suffix}").write_text(case_yaml, encoding="utf-8")
    return eval_dir
