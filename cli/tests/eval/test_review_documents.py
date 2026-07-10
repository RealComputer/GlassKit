from __future__ import annotations

import shutil
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from glasskit.eval.expectations import load_eval_suite
from glasskit.eval.review.documents import ReviewRepository
from glasskit.eval.review.models import (
    PointCompare,
    ReplaceSamplesRequest,
    ReviewAPIError,
    ReviewPoint,
    TargetReplacement,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_suite_index_is_case_local_and_document_contains_lossless_points(
    tmp_path: Path,
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    malformed = eval_dir / "cases" / "malformed.yaml"
    malformed.write_text("targets: [\n", encoding="utf-8")
    invalid_encoding = eval_dir / "cases" / "invalid-encoding.yaml"
    invalid_encoding.write_bytes(b"video: \xff\n")
    repository = ReviewRepository(eval_dir)

    suite = repository.suite_document(write_token="secret")
    assembly = repository.case_document("assembly.yaml")

    assert suite.write_token == "secret"
    assert [case.id for case in suite.cases] == [
        "assembly.yaml",
        "inspection.yml",
        "invalid-encoding.yaml",
        "malformed.yaml",
    ]
    assert suite.cases[-2].status == "blocked"
    assert suite.cases[-2].error is not None
    assert suite.cases[-2].error.code == "invalid_encoding"
    assert suite.cases[-1].status == "blocked"
    assert suite.cases[-1].point_count is None
    assert assembly.status == "ready"
    assert assembly.editing_enabled
    assert assembly.source_yaml.startswith("video:")
    assert assembly.video is not None
    assert assembly.video.url == "/api/cases/assembly.yaml/video"
    assert assembly.targets[0].details_yaml == "config:\n  confidence_floor: 0.75\n"
    assert assembly.targets[0].points[0].expect_json == "false"
    assert assembly.targets[0].points[0].origin is not None
    assert assembly.targets[0].display_groups[0].kind == "range"


def test_video_probe_failure_retains_normalized_targets(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "assembly.yaml"
    source = path.read_text(encoding="utf-8").replace(
        "../../../videos/two-state-64x64.mp4", "missing.mp4"
    )
    path.write_text(source, encoding="utf-8")

    document = ReviewRepository(eval_dir).case_document("assembly.yaml")

    assert document.status == "blocked"
    assert not document.editing_enabled
    assert document.load_error is not None
    assert document.load_error.code == "video_unavailable"
    assert [len(target.points) for target in document.targets] == [4, 5]
    assert document.video is not None
    assert document.video.display_path == "missing.mp4"
    assert document.video.duration_s is None


def test_surrogate_source_text_is_isolated_as_a_blocked_case(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "surrogate.yaml"
    path.write_text(
        """video: ../../../videos/two-state-64x64.mp4
description: "\\uD800"
targets:
  state:
    samples:
      - at: 0.0
        expect: "\\uD800"
""",
        encoding="utf-8",
    )
    repository = ReviewRepository(eval_dir)

    suite = repository.suite_document(write_token="secret")
    summary = next(case for case in suite.cases if case.id == "surrogate.yaml")
    document = repository.case_document("surrogate.yaml")

    assert summary.status == "blocked"
    assert summary.error is not None
    assert "Unicode scalar" in summary.error.message
    assert document.status == "blocked"
    assert document.load_error is not None
    assert "Unicode scalar" in document.load_error.message


def test_recursive_yaml_is_isolated_as_a_blocked_case(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "recursive.yaml"
    path.write_text(
        "metadata: " + "[" * 600 + "null" + "]" * 600,
        encoding="utf-8",
    )
    repository = ReviewRepository(eval_dir)

    suite = repository.suite_document(write_token="secret")
    summary = next(case for case in suite.cases if case.id == "recursive.yaml")
    document = repository.case_document("recursive.yaml")

    valid_summary = next(case for case in suite.cases if case.id == "assembly.yaml")

    assert valid_summary.status == "ready"
    assert summary.status == "blocked"
    assert summary.error is not None
    assert summary.error.code == "invalid_case"
    assert document.status == "blocked"
    assert document.load_error is not None
    assert document.load_error.code == "invalid_case"


def test_empty_and_over_duration_targets_are_repairable(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "assembly.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["targets"]["bracket_seated"]["samples"] = []
    raw["targets"]["evidence"]["samples"][0]["range"] = [2.1, 2.6]
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    document = ReviewRepository(eval_dir).case_document("assembly.yaml")

    assert document.status == "repairable"
    assert document.editing_enabled
    assert {issue.code for issue in document.validation_issues} == {
        "empty_target",
        "timestamp_after_video",
    }


def test_huge_finite_points_are_repairable_without_range_overflow(
    tmp_path: Path,
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "huge.yaml"
    path.write_text(
        """video: ../../../videos/two-state-64x64.mp4
sampling:
  every_s: 6.0e+307
targets:
  state:
    samples:
      - at: [1.0e+308, 1.6e+308]
        expect: true
""",
        encoding="utf-8",
    )

    document = ReviewRepository(eval_dir).case_document("huge.yaml")

    assert document.status == "repairable"
    assert [point.timestamp_s for point in document.targets[0].points] == [
        1e308,
        1.6e308,
    ]
    assert document.targets[0].display_groups[0].kind == "at"
    assert {issue.code for issue in document.validation_issues} == {
        "timestamp_after_video"
    }


def test_atomic_multi_target_write_preserves_metadata_ids_and_permissions(
    tmp_path: Path,
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "assembly.yaml"
    path.chmod(0o640)
    repository = ReviewRepository(eval_dir)
    before = repository.case_document("assembly.yaml")
    bracket = before.targets[0]
    evidence = before.targets[1]
    bracket_points = list(bracket.points)
    evidence_points = list(evidence.points)
    bracket_points[0] = bracket_points[0].model_copy(update={"timestamp_s": 0.1})
    evidence_points[-1] = evidence_points[-1].model_copy(
        update={"comment": "Updated evidence comment."}
    )
    request = ReplaceSamplesRequest(
        targets={
            bracket.id: TargetReplacement(points=bracket_points),
            evidence.id: TargetReplacement(points=evidence_points),
        }
    )

    accepted = repository.replace_samples("assembly.yaml", request)

    assert accepted.status == "ready"
    assert accepted.targets[0].points[0].timestamp_s == 0.1
    assert accepted.targets[0].points[0].id == bracket.points[0].id
    assert accepted.targets[1].points[-1].comment == "Updated evidence comment."
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    rendered = path.read_text(encoding="utf-8")
    assert "review_hint: Look for the green second state." in rendered
    assert "range: [" in rendered
    assert "at: [" in rendered
    # The normal eval loader is the final semantic compatibility check.
    load_eval_suite(eval_dir)


def test_invalid_candidate_leaves_original_bytes_untouched(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "assembly.yaml"
    repository = ReviewRepository(eval_dir)
    document = repository.case_document("assembly.yaml")
    original = path.read_bytes()
    request = ReplaceSamplesRequest(
        targets={document.targets[0].id: TargetReplacement(points=[])}
    )

    with pytest.raises(ReviewAPIError) as raised:
        repository.replace_samples("assembly.yaml", request)

    assert raised.value.status == 422
    assert path.read_bytes() == original


def test_put_after_case_becomes_non_utf8_is_a_conflict(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "assembly.yaml"
    repository = ReviewRepository(eval_dir)
    document = repository.case_document("assembly.yaml")
    request = ReplaceSamplesRequest(
        targets={
            document.targets[0].id: TargetReplacement(points=document.targets[0].points)
        }
    )
    invalid_bytes = b"video: \xff\n"
    path.write_bytes(invalid_bytes)

    with pytest.raises(ReviewAPIError) as raised:
        repository.replace_samples("assembly.yaml", request)

    assert raised.value.status == 409
    assert raised.value.code == "case_structure_changed"
    assert path.read_bytes() == invalid_bytes


def test_one_batch_repairs_two_empty_targets(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "assembly.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for target in raw["targets"].values():
        target["samples"] = []
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    repository = ReviewRepository(eval_dir)
    assert repository.case_document("assembly.yaml").status == "repairable"

    request = ReplaceSamplesRequest(
        targets={
            "bracket_seated": TargetReplacement(
                points=[_new_point("shared-id", 0.0, "false", "boolean")]
            ),
            "evidence": TargetReplacement(
                points=[_new_point("shared-id", 0.0, '{"count":1}', "object")]
            ),
        }
    )
    accepted = repository.replace_samples("assembly.yaml", request)

    assert accepted.status == "ready"
    assert [len(target.points) for target in accepted.targets] == [1, 1]
    load_eval_suite(eval_dir)


def test_unknown_case_and_target_have_distinct_conflict_statuses(
    tmp_path: Path,
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    repository = ReviewRepository(eval_dir)

    with pytest.raises(ReviewAPIError) as missing_case:
        repository.case_document("../assembly.yaml")
    assert missing_case.value.status == 404

    request = ReplaceSamplesRequest(
        targets={
            "not-present": TargetReplacement(
                points=[_new_point("point", 0.0, "true", "boolean")]
            )
        }
    )
    with pytest.raises(ReviewAPIError) as missing_target:
        repository.replace_samples("assembly.yaml", request)
    assert missing_target.value.status == 409


def test_concurrent_target_batches_preserve_both_accepted_changes(
    tmp_path: Path,
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    repository = ReviewRepository(eval_dir)
    document = repository.case_document("assembly.yaml")
    bracket_points = list(document.targets[0].points)
    evidence_points = list(document.targets[1].points)
    bracket_points[0] = bracket_points[0].model_copy(
        update={"comment": "Concurrent bracket edit."}
    )
    evidence_points[0] = evidence_points[0].model_copy(
        update={"comment": "Concurrent evidence edit."}
    )
    requests = [
        ReplaceSamplesRequest(
            targets={"bracket_seated": TargetReplacement(points=bracket_points)}
        ),
        ReplaceSamplesRequest(
            targets={"evidence": TargetReplacement(points=evidence_points)}
        ),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        accepted = list(
            executor.map(
                lambda request: repository.replace_samples("assembly.yaml", request),
                requests,
            )
        )

    assert all(document.status == "ready" for document in accepted)
    current = repository.case_document("assembly.yaml")
    assert current.targets[0].points[0].comment == "Concurrent bracket edit."
    assert current.targets[1].points[0].comment == "Concurrent evidence edit."


def test_directory_sync_failure_returns_accepted_document_warning(
    tmp_path: Path, monkeypatch
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    repository = ReviewRepository(eval_dir)
    document = repository.case_document("assembly.yaml")
    points = list(document.targets[0].points)
    points[0] = points[0].model_copy(update={"timestamp_s": 0.1})
    monkeypatch.setattr(
        "glasskit.eval.review.serialization._sync_directory", lambda _path: True
    )

    accepted = repository.replace_samples(
        "assembly.yaml",
        ReplaceSamplesRequest(
            targets={"bracket_seated": TargetReplacement(points=points)}
        ),
    )

    assert accepted.status == "ready"
    assert accepted.targets[0].points[0].timestamp_s == 0.1
    assert [issue.code for issue in accepted.validation_issues] == [
        "directory_sync_failed"
    ]


def test_unrelated_timestamp_edit_preserves_lossless_nested_expectation(
    tmp_path: Path,
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "assembly.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    expected = {
        "large": 900719925474099312345,
        "integer": 1,
        "float": 1.0,
        "negative_zero": -0.0,
    }
    raw["targets"]["evidence"]["samples"][0]["expect"] = expected
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    repository = ReviewRepository(eval_dir)
    document = repository.case_document("assembly.yaml")
    evidence = document.targets[1]
    assert evidence.points[0].expect_json == (
        '{"large":900719925474099312345,"integer":1,"float":1.0,"negative_zero":-0.0}'
    )
    points = list(evidence.points)
    points[0] = points[0].model_copy(update={"timestamp_s": 0.05})

    repository.replace_samples(
        "assembly.yaml",
        ReplaceSamplesRequest(targets={"evidence": TargetReplacement(points=points)}),
    )

    reloaded = ReviewRepository(eval_dir).case_document("assembly.yaml")
    assert reloaded.targets[1].points[0].expect_json == (
        '{"large":900719925474099312345,"integer":1,"float":1.0,"negative_zero":-0.0}'
    )


def test_writer_does_not_insert_omitted_case_or_target_defaults(
    tmp_path: Path,
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    path = eval_dir / "cases" / "minimal.yaml"
    path.write_text(
        """video: ../../../videos/two-state-64x64.mp4
targets:
  state:
    samples:
      - at: 0.0
        expect: null
""",
        encoding="utf-8",
    )
    repository = ReviewRepository(eval_dir)
    document = repository.case_document("minimal.yaml")
    points = list(document.targets[0].points)
    points[0] = points[0].model_copy(update={"timestamp_s": 0.1})

    repository.replace_samples(
        "minimal.yaml",
        ReplaceSamplesRequest(targets={"state": TargetReplacement(points=points)}),
    )

    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert list(written) == ["video", "targets"]
    assert list(written["targets"]["state"]) == ["samples"]
    assert written["targets"]["state"]["samples"] == [{"at": 0.1, "expect": None}]


def _copy_fixtures(tmp_path: Path) -> Path:
    destination = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, destination)
    return destination / "eval_suites" / "review"


def _new_point(
    point_id: str, timestamp_s: float, expect_json: str, expect_type: str
) -> ReviewPoint:
    return ReviewPoint.model_validate(
        {
            "id": point_id,
            "timestamp_s": timestamp_s,
            "expect_type": expect_type,
            "expect_json": expect_json,
            "field": None,
            "compare": PointCompare().model_dump(),
            "comment": None,
            "origin": None,
        }
    )
