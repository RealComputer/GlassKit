from __future__ import annotations

import shutil
from dataclasses import dataclass
from json import dumps as json_dumps
from pathlib import Path

from .expectations import SUPPORTED_VIDEO_SUFFIXES
from .models import EvalConfigError


@dataclass(frozen=True)
class InitCaseResult:
    case_dir: Path
    expected_path: Path
    video_path: Path


def init_eval_case(
    *,
    suite_path: Path,
    case_name: str,
    source_video: Path,
    target_id: str,
    target_label: str | None = None,
    force: bool = False,
) -> InitCaseResult:
    case_name = case_name.strip()
    target_id = target_id.strip()
    if not case_name:
        raise EvalConfigError("case name must not be empty")
    if Path(case_name).name != case_name:
        raise EvalConfigError("case name must be a single directory name")
    if not target_id:
        raise EvalConfigError("target id must not be empty")

    suite_path = suite_path.expanduser().resolve()
    source_video = source_video.expanduser().resolve()
    if not source_video.exists() or not source_video.is_file():
        raise EvalConfigError(f"video file does not exist: {source_video}")
    if source_video.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        raise EvalConfigError(f"unsupported video file type: {source_video}")

    if suite_path.exists() and not suite_path.is_dir():
        raise EvalConfigError(f"eval suite path is not a directory: {suite_path}")
    case_dir = suite_path / case_name
    if case_dir.exists() and not case_dir.is_dir():
        raise EvalConfigError(f"case path is not a directory: {case_dir}")
    expected_path = case_dir / "expected.yaml"
    case_dir.mkdir(parents=True, exist_ok=True)
    if expected_path.exists() and not force:
        raise EvalConfigError(f"expected.yaml already exists: {expected_path}")

    video_path = _case_video_path(case_dir, source_video)
    if video_path.exists() and not _same_file(source_video, video_path) and not force:
        raise EvalConfigError(f"case video already exists: {video_path}")
    if not _same_file(source_video, video_path):
        shutil.copy2(source_video, video_path)

    expected_path.write_text(
        _expected_yaml_template(
            video_name=video_path.name,
            target_id=target_id,
            target_label=target_label.strip() if target_label else None,
        ),
        encoding="utf-8",
    )
    return InitCaseResult(
        case_dir=case_dir,
        expected_path=expected_path,
        video_path=video_path,
    )


def _case_video_path(case_dir: Path, source_video: Path) -> Path:
    try:
        source_video.relative_to(case_dir)
    except ValueError:
        return case_dir / f"video{source_video.suffix.lower()}"
    return source_video


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return False


def _expected_yaml_template(
    *, video_name: str, target_id: str, target_label: str | None
) -> str:
    label_line = f"    label: {_yaml_string(target_label)}\n" if target_label else ""
    return (
        "version: 1\n"
        f"video: {_yaml_string(video_name)}\n"
        "description: "
        '"Starter eval case. Replace the sample timestamps and expected values '
        'with stable labeled windows from this video."\n'
        "sampling:\n"
        "  every_s: 0.5\n"
        "targets:\n"
        f"  {_yaml_string(target_id)}:\n"
        f"{label_line}"
        "    samples:\n"
        "      - at: 0.0\n"
        "        expect: false\n"
        "      # Prefer stable, unambiguous ranges for real evals:\n"
        "      # - range: [1.0, 3.0]\n"
        "      #   expect: true\n"
    )


def _yaml_string(value: str) -> str:
    return json_dumps(value, ensure_ascii=True)
