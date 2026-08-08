from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from rich.text import Text
from typer.testing import CliRunner

from glasskit.cli import app
from glasskit.eval.frame_export import export_case_frames
from glasskit.eval.models import EvalConfigError
from glasskit.eval.video import iter_frames_at

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REVIEW_EVAL_DIR = FIXTURES / "eval_directories" / "review"


def test_export_case_frames_writes_lossless_pngs_in_requested_order(
    tmp_path: Path,
) -> None:
    paths = export_case_frames(
        REVIEW_EVAL_DIR,
        case_selector="assembly",
        timestamps_s=[1.0, 0.0, 1.0],
        output_dir=tmp_path / "frames",
    )

    assert [path.name for path in paths] == ["at-1.0s.png", "at-0.0s.png"]
    selected_frames = iter_frames_at(
        FIXTURES / "videos" / "two-state-64x64.mp4", [1.0, 0.0]
    )
    expected_by_request: dict[int, bytes] = {}
    try:
        for selected in selected_frames:
            expected_by_request[selected.request_index] = selected.image.tobytes()
            selected.image.close()
    finally:
        selected_frames.close()

    for request_index, path in enumerate(paths):
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.mode == "RGB"
            assert image.size == (64, 64)
            assert image.tobytes() == expected_by_request[request_index]


def test_export_case_frames_supports_draft_cases_and_arbitrary_times(
    tmp_path: Path,
) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    video_path = FIXTURES / "videos" / "two-state-64x64.mp4"
    (cases_dir / "draft.yaml").write_text(
        f"""
video: {video_path.as_posix()}
targets:
  state:
    samples:
      - at: 0.0
""",
        encoding="utf-8",
    )

    paths = export_case_frames(
        eval_dir,
        case_selector="draft.yaml",
        timestamps_s=[0.75],
    )

    assert paths == [eval_dir.resolve() / "runs/frames/draft/at-0.75s.png"]
    assert paths[0].is_file()


@pytest.mark.parametrize("timestamp_s", [float("nan"), float("inf"), -0.1])
def test_export_case_frames_rejects_invalid_times(timestamp_s: float) -> None:
    with pytest.raises(
        EvalConfigError, match="--at must be a finite, nonnegative number"
    ):
        export_case_frames(
            REVIEW_EVAL_DIR,
            case_selector="assembly",
            timestamps_s=[timestamp_s],
        )


def test_export_case_frames_rejects_times_after_the_video() -> None:
    with pytest.raises(EvalConfigError, match="exceeds video duration"):
        export_case_frames(
            REVIEW_EVAL_DIR,
            case_selector="assembly",
            timestamps_s=[2.001],
        )


def test_export_frames_cli_prints_only_output_paths(tmp_path: Path) -> None:
    output_dir = tmp_path / "frames"

    result = CliRunner().invoke(
        app,
        [
            "eval",
            "export-frames",
            "--eval-dir",
            str(REVIEW_EVAL_DIR),
            "--case",
            "assembly",
            "--at",
            "1.0",
            "--at",
            "0.0",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert result.output == (
        f"{output_dir.resolve() / 'at-1.0s.png'}\n"
        f"{output_dir.resolve() / 'at-0.0s.png'}\n"
    )


def test_export_frames_cli_reports_export_errors() -> None:
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "export-frames",
            "--eval-dir",
            str(REVIEW_EVAL_DIR),
            "--case",
            "assembly",
            "--at",
            "3.0",
        ],
    )

    assert result.exit_code == 2
    assert "Could not export frames:" in Text.from_ansi(result.output).plain
    assert "exceeds video duration" in Text.from_ansi(result.output).plain
