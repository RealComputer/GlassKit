from __future__ import annotations

from pathlib import Path

import pytest

from glasskit.eval.expectations import (
    MAX_EXPANDED_SAMPLES_PER_CASE,
    discover_case_paths,
    load_case,
    load_eval_directory,
    load_yaml_mapping,
)
from glasskit.eval.models import EvalConfigError
from glasskit.eval.schemas import parse_case_file


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

    eval_directory = load_eval_directory(eval_dir)

    samples = eval_directory.cases[0].samples
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

    eval_directory = load_eval_directory(eval_dir)

    assert [sample.timestamp_s for sample in eval_directory.cases[0].samples] == [
        1.0,
        2.0,
        3.0,
        4.0,
    ]


def test_sample_comment_is_trimmed_and_expands_to_every_sample(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, 1.0]
                expect: true
                comment: |-
                  First line.
                  Second line.
              - at: 2.0
                expect: false
        """,
    )

    samples = load_eval_directory(eval_dir).cases[0].samples

    assert [sample.comment for sample in samples] == [
        "First line.\nSecond line.",
        "First line.\nSecond line.",
        None,
    ]


def test_blank_sample_comment_is_invalid(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: true
                comment: "   "
        """,
    )

    with pytest.raises(
        EvalConfigError, match=r"samples\.0\.comment.*must not be empty"
    ):
        load_eval_directory(eval_dir)


def test_sample_ignore_reason_is_trimmed_and_expands_to_every_sample(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: [0.0, 0.5]
                expect: true
                ignore: "  Known flaky observation.  "
              - at: 1.0
                expect: true
        """,
    )

    samples = load_eval_directory(eval_dir).cases[0].samples

    assert [sample.ignore for sample in samples] == [
        "Known flaky observation.",
        "Known flaky observation.",
        None,
    ]


def test_blank_sample_ignore_reason_is_invalid(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: 0.0
                expect: true
                ignore: "   "
        """,
    )

    with pytest.raises(EvalConfigError, match=r"samples\.0\.ignore.*must not be empty"):
        load_eval_directory(eval_dir)


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

    eval_directory = load_eval_directory(eval_dir)

    assert [sample.timestamp_s for sample in eval_directory.cases[0].samples] == [
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
        load_eval_directory(eval_dir)


def test_sample_inside_range_is_invalid(tmp_path: Path) -> None:
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
        load_eval_directory(eval_dir)


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
        load_eval_directory(eval_dir)


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
        load_eval_directory(eval_dir)


def test_huge_finite_timestamp_loads_without_tick_overflow(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: 1.0e308
                expect: true
        """,
    )

    eval_directory = load_eval_directory(eval_dir)

    assert eval_directory.samples[0].timestamp_s == 1.0e308


def test_range_expansion_budget_is_checked_before_materialization(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        f"""
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, {MAX_EXPANDED_SAMPLES_PER_CASE + 1}.0]
                every_s: 1.0
                expect: true
        """,
    )

    with pytest.raises(
        EvalConfigError,
        match=(
            rf"target 'step_1' sample 1 would expand the case to "
            rf"{MAX_EXPANDED_SAMPLES_PER_CASE + 1} samples; limit is "
            rf"{MAX_EXPANDED_SAMPLES_PER_CASE}"
        ),
    ):
        load_eval_directory(eval_dir)


def test_range_at_budget_uses_repeated_addition_count(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, 1000.000000001001]
                every_s: 0.1
                expect: true
        """,
    )

    eval_directory = load_eval_directory(eval_dir)

    assert len(eval_directory.cases[0].samples) == MAX_EXPANDED_SAMPLES_PER_CASE
    assert eval_directory.cases[0].samples[-1].timestamp_s == 999.9


def test_sub_nanosecond_cadence_hits_budget_before_expansion(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, 0.00001]
                every_s: 0.0000000001
                expect: true
        """,
    )

    with pytest.raises(EvalConfigError, match=r"would expand.*limit is 10000"):
        load_eval_directory(eval_dir)


def test_expansion_budget_is_shared_across_targets(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          first:
            samples:
              - range: [0.0, 6000.0]
                every_s: 1.0
                expect: true
          second:
            samples:
              - range: [0.0, 4001.0]
                every_s: 1.0
                expect: false
        """,
    )

    with pytest.raises(
        EvalConfigError,
        match=r"target 'second' sample 1.*case to 10001 samples.*limit is 10000",
    ):
        load_eval_directory(eval_dir)


def test_range_rejects_duplicates_after_timestamp_normalization(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, 0.000001]
                every_s: 0.0000000005
                expect: true
        """,
    )

    with pytest.raises(
        EvalConfigError, match="duplicates timestamp.*nine-decimal normalization"
    ):
        load_eval_directory(eval_dir)


def test_at_rejects_near_duplicates_after_timestamp_normalization(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: [0.0, 0.000000001]
                expect: true
        """,
    )

    with pytest.raises(EvalConfigError, match="duplicates timestamp"):
        load_eval_directory(eval_dir)


def test_target_rejects_cross_block_near_duplicates_after_normalization(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - range: [0.0, 1.0000000012]
                every_s: 1.0
                expect: false
              - range: [1.0000000012, 1.5000000012]
                every_s: 0.5
                expect: true
        """,
    )

    with pytest.raises(
        EvalConfigError,
        match=r"target 'step_1' timestamps.*within 1e-9 seconds",
    ):
        load_eval_directory(eval_dir)


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
        load_eval_directory(eval_dir)


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
        load_eval_directory(eval_dir)


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
        load_eval_directory(eval_dir)


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

    eval_directory = load_eval_directory(eval_dir)

    assert [case.name for case in eval_directory.cases] == ["case-001"]


def test_public_case_helpers_support_review_loading_without_a_video(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: missing.mp4
        targets:
          step_1:
            samples:
              - at: [0.0, 1.0]
                expect: true
                comment: Reviewable without preview.
        """,
    )
    case_path = discover_case_paths(eval_dir)[0]
    raw_case = parse_case_file(load_yaml_mapping(case_path), label=str(case_path))

    case = load_case(case_path, raw_case=raw_case, resolve_video=False)

    assert case.video_path == (case_path.parent / "missing.mp4").resolve()
    assert [sample.timestamp_s for sample in case.samples] == [0.0, 1.0]
    assert [sample.comment for sample in case.samples] == [
        "Reviewable without preview.",
        "Reviewable without preview.",
    ]
    with pytest.raises(EvalConfigError, match="video file does not exist"):
        load_case(case_path, raw_case=raw_case)


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

    eval_directory = load_eval_directory(eval_dir, case_filter="case-001")

    assert eval_directory.cases[0].path.name == "case-001.yml"


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

    eval_directory = load_eval_directory(eval_dir, case_filter="case-001.yaml")

    assert eval_directory.cases[0].name == "case-001"


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

    eval_directory = load_eval_directory(eval_dir, case_filter="case-001.yml")

    assert eval_directory.cases[0].name == "case-001"


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

    eval_directory = load_eval_directory(
        eval_dir, case_filter="case-001", target_filter="step_2"
    )

    case = eval_directory.cases[0]
    assert [target.id for target in case.targets] == ["step_2"]
    assert [sample.target_id for sample in case.samples] == ["step_2", "step_2"]
    assert [sample.sample_index for sample in case.samples] == [1, 2]


def test_target_filter_selects_multiple_targets_in_case_file_order(
    tmp_path: Path,
) -> None:
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
              - at: 1.0
                expect: true
          step_3:
            samples:
              - at: 2.0
                expect: true
        """,
    )

    eval_directory = load_eval_directory(
        eval_dir,
        case_filter="case-001",
        target_filter=("step_2", "step_1", "step_2"),
    )

    case = eval_directory.cases[0]
    assert [target.id for target in case.targets] == ["step_1", "step_2"]
    assert [sample.target_id for sample in case.samples] == ["step_1", "step_2"]


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

    eval_directory = load_eval_directory(eval_dir, target_filter="step_2")

    assert [case.name for case in eval_directory.cases] == ["case-002"]
    assert [target.id for target in eval_directory.cases[0].targets] == ["step_2"]


def test_multiple_target_filter_without_case_keeps_matching_case_union(
    tmp_path: Path,
) -> None:
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
    (eval_dir / "cases" / "case-003.yaml").write_text(
        """
        video: missing.mp4
        targets:
          step_3:
            samples:
              - at: 2.0
                expect: true
        """,
        encoding="utf-8",
    )

    eval_directory = load_eval_directory(eval_dir, target_filter=("step_2", "step_1"))

    assert [case.name for case in eval_directory.cases] == ["case-001", "case-002"]
    assert [target.id for case in eval_directory.cases for target in case.targets] == [
        "step_1",
        "step_2",
    ]


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

    eval_directory = load_eval_directory(eval_dir, target_filter="step_2")

    assert [case.name for case in eval_directory.cases] == ["case-002"]


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
        load_eval_directory(eval_dir, target_filter="step_2")


def test_multiple_target_filter_errors_when_any_target_is_missing(
    tmp_path: Path,
) -> None:
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
        load_eval_directory(eval_dir, target_filter=("step_1", "step_2"))


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
        load_eval_directory(eval_dir, target_filter="")


def test_time_window_filter_uses_inclusive_from_and_exclusive_until(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: [0.0, 1.0, 2.0, 3.0]
                expect: true
          step_2:
            samples:
              - at: 0.5
                expect: false
        """,
    )

    eval_directory = load_eval_directory(
        eval_dir,
        case_filter="case-001",
        from_time_s=1.0,
        until_time_s=3.0,
    )

    case = eval_directory.cases[0]
    assert [target.id for target in case.targets] == ["step_1", "step_2"]
    assert case.targets[1].samples == []
    assert [sample.timestamp_s for sample in case.samples] == [1.0, 2.0]
    assert [sample.sample_index for sample in case.samples] == [1, 2]


def test_time_window_filter_supports_one_sided_bounds(tmp_path: Path) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: [0.0, 1.0, 2.0, 3.0]
                expect: true
        """,
    )

    from_directory = load_eval_directory(
        eval_dir,
        case_filter="case-001",
        from_time_s=2.0,
    )
    until_directory = load_eval_directory(
        eval_dir,
        case_filter="case-001",
        until_time_s=2.0,
    )

    assert [sample.timestamp_s for sample in from_directory.samples] == [2.0, 3.0]
    assert [sample.timestamp_s for sample in until_directory.samples] == [0.0, 1.0]


def test_time_window_filter_requires_case(tmp_path: Path) -> None:
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

    with pytest.raises(EvalConfigError, match="--from and --until require --case"):
        load_eval_directory(eval_dir, from_time_s=0.0)


@pytest.mark.parametrize(
    ("from_time_s", "until_time_s", "message"),
    [
        (-1.0, None, "--from must be a finite, nonnegative number"),
        (float("inf"), None, "--from must be a finite, nonnegative number"),
        (2.0, 2.0, "--from must be less than --until"),
        (3.0, 2.0, "--from must be less than --until"),
    ],
)
def test_time_window_filter_rejects_invalid_bounds(
    tmp_path: Path,
    from_time_s: float | None,
    until_time_s: float | None,
    message: str,
) -> None:
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

    with pytest.raises(EvalConfigError, match=message):
        load_eval_directory(
            eval_dir,
            case_filter="case-001",
            from_time_s=from_time_s,
            until_time_s=until_time_s,
        )


def test_time_window_filter_rejects_an_empty_selection_even_when_empty_is_allowed(
    tmp_path: Path,
) -> None:
    eval_dir = _eval_dir(
        tmp_path,
        """
        video: video.mp4
        targets:
          step_1:
            samples:
              - at: [0.0, 1.0]
                expect: true
        """,
    )

    with pytest.raises(EvalConfigError, match="no eval samples found at or after 2"):
        load_eval_directory(
            eval_dir,
            case_filter="case-001",
            from_time_s=2.0,
            allow_empty=True,
        )


def test_uppercase_file_case_suffix_is_ignored(tmp_path: Path) -> None:
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

    with pytest.raises(EvalConfigError, match="no case files found"):
        load_eval_directory(eval_dir)


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

    with pytest.raises(EvalConfigError, match="multiple case files"):
        load_eval_directory(eval_dir)


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

    eval_directory = load_eval_directory(eval_dir)

    assert eval_directory.thresholds.min_pass_rate == 0.9
    assert eval_directory.thresholds.max_failures == 2
    assert eval_directory.thresholds.per_target["step_1"].min_pass_rate == 0.95


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

    eval_directory = load_eval_directory(eval_dir)

    assert eval_directory.thresholds.min_pass_rate == 0.9


def test_uppercase_file_config_suffix_is_ignored(tmp_path: Path) -> None:
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

    eval_directory = load_eval_directory(eval_dir)

    assert eval_directory.thresholds.min_pass_rate is None


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
        load_eval_directory(eval_dir)


def _eval_dir(tmp_path: Path, case_file: str, *, case_suffix: str = ".yaml") -> Path:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "video.mp4").write_bytes(b"placeholder")
    (cases_dir / f"case-001{case_suffix}").write_text(case_file, encoding="utf-8")
    return eval_dir
