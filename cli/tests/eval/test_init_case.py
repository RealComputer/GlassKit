from __future__ import annotations

from pathlib import Path

import pytest

from gk.eval.expectations import load_eval_suite
from gk.eval.init_case import init_eval_case
from gk.eval.models import EvalConfigError


def test_init_case_copies_video_and_writes_expected_yaml(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")

    result = init_eval_case(
        suite_path=tmp_path / "suite",
        case_name="fold-step-001",
        source_video=source_video,
        target_id="step_1",
        target_label="Step 1",
    )

    assert result.video_path == tmp_path / "suite" / "fold-step-001" / "video.mp4"
    assert result.video_path.read_bytes() == b"fake video"
    expected = result.expected_path.read_text(encoding="utf-8")
    assert 'video: "video.mp4"' in expected
    assert '  "step_1":' in expected
    assert '    label: "Step 1"' in expected

    suite = load_eval_suite(tmp_path / "suite")
    assert suite.cases[0].name == "fold-step-001"
    assert suite.cases[0].targets[0].id == "step_1"


def test_init_case_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    init_eval_case(
        suite_path=tmp_path / "suite",
        case_name="case-001",
        source_video=source_video,
        target_id="step_1",
    )

    with pytest.raises(EvalConfigError, match="expected.yaml already exists"):
        init_eval_case(
            suite_path=tmp_path / "suite",
            case_name="case-001",
            source_video=source_video,
            target_id="step_1",
        )


def test_init_case_uses_video_already_inside_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "suite" / "case-001"
    case_dir.mkdir(parents=True)
    source_video = case_dir / "recording.mov"
    source_video.write_bytes(b"fake video")

    result = init_eval_case(
        suite_path=tmp_path / "suite",
        case_name="case-001",
        source_video=source_video,
        target_id="detector.ready",
    )

    assert result.video_path == source_video
    expected = result.expected_path.read_text(encoding="utf-8")
    assert 'video: "recording.mov"' in expected
    assert '  "detector.ready":' in expected
