from __future__ import annotations

from pathlib import Path

import pytest

from glasskit.eval.expectations import load_eval_suite
from glasskit.eval.init_case import init_eval_case
from glasskit.eval.models import EvalConfigError


def test_init_case_copies_video_and_writes_case_yaml(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")

    result = init_eval_case(
        eval_dir=tmp_path / "eval",
        case_name="fold-step-001",
        source_video=source_video,
        target_id="step_1",
        target_label="Step 1",
    )

    assert result.eval_dir == tmp_path / "eval"
    assert result.case_path == tmp_path / "eval" / "cases" / "fold-step-001.yaml"
    assert result.video_path == tmp_path / "eval" / "cases" / "fold-step-001.mp4"
    assert result.video_path.read_bytes() == b"fake video"
    case_yaml = result.case_path.read_text(encoding="utf-8")
    assert 'video: "fold-step-001.mp4"' in case_yaml
    assert '  "step_1":' in case_yaml
    assert '    label: "Step 1"' in case_yaml

    suite = load_eval_suite(tmp_path / "eval")
    assert suite.cases[0].name == "fold-step-001"
    assert suite.cases[0].targets[0].id == "step_1"


def test_init_case_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    init_eval_case(
        eval_dir=tmp_path / "eval",
        case_name="case-001",
        source_video=source_video,
        target_id="step_1",
    )

    with pytest.raises(EvalConfigError, match="case YAML already exists"):
        init_eval_case(
            eval_dir=tmp_path / "eval",
            case_name="case-001",
            source_video=source_video,
            target_id="step_1",
        )


def test_init_case_rejects_parent_directory_case_name(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")

    with pytest.raises(EvalConfigError, match="case name must be a single filename"):
        init_eval_case(
            eval_dir=tmp_path / "eval",
            case_name="..",
            source_video=source_video,
            target_id="step_1",
        )

    assert not (tmp_path / "eval" / "cases").exists()


def test_init_case_uses_video_already_inside_cases_dir(tmp_path: Path) -> None:
    cases_dir = tmp_path / "eval" / "cases"
    cases_dir.mkdir(parents=True)
    source_video = cases_dir / "recording.mov"
    source_video.write_bytes(b"fake video")

    result = init_eval_case(
        eval_dir=tmp_path / "eval",
        case_name="case-001",
        source_video=source_video,
        target_id="detector.ready",
    )

    assert result.video_path == source_video
    case_yaml = result.case_path.read_text(encoding="utf-8")
    assert 'video: "recording.mov"' in case_yaml
    assert '  "detector.ready":' in case_yaml


def test_init_case_preserves_video_path_inside_eval_dir(
    tmp_path: Path,
) -> None:
    videos_dir = tmp_path / "eval" / "videos"
    videos_dir.mkdir(parents=True)
    source_video = videos_dir / "recording.mp4"
    source_video.write_bytes(b"fake video")

    result = init_eval_case(
        eval_dir=tmp_path / "eval",
        case_name="case-001",
        source_video=source_video,
        target_id="detector.ready",
    )

    assert result.video_path == source_video
    case_yaml = result.case_path.read_text(encoding="utf-8")
    assert 'video: "../videos/recording.mp4"' in case_yaml

    suite = load_eval_suite(tmp_path / "eval")
    assert suite.cases[0].video_path == source_video.resolve()
