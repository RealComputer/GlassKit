from __future__ import annotations

import shutil
from dataclasses import dataclass
from json import dumps as json_dumps
from os import path as os_path
from pathlib import Path

from .expectations import SUPPORTED_VIDEO_SUFFIXES
from .models import EvalConfigError


@dataclass(frozen=True)
class InitCaseResult:
    eval_dir: Path
    case_path: Path
    video_path: Path


def init_eval_case(
    *,
    eval_dir: Path,
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
    if (
        case_name in {".", ".."}
        or Path(case_name).name != case_name
        or case_name.endswith((".yaml", ".yml"))
    ):
        raise EvalConfigError("case name must be a single filename stem")
    if not target_id:
        raise EvalConfigError("target id must not be empty")

    eval_dir = eval_dir.expanduser().resolve()
    source_video = source_video.expanduser().resolve()
    if not source_video.exists() or not source_video.is_file():
        raise EvalConfigError(f"video file does not exist: {source_video}")
    if source_video.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        raise EvalConfigError(f"unsupported video file type: {source_video}")

    if eval_dir.exists() and not eval_dir.is_dir():
        raise EvalConfigError(f"eval path is not a directory: {eval_dir}")
    cases_dir = (eval_dir / "cases").resolve()
    case_path = (cases_dir / f"{case_name}.yaml").resolve()
    try:
        case_path.relative_to(eval_dir)
    except ValueError as exc:
        raise EvalConfigError("case path must stay inside the eval directory") from exc
    cases_dir.mkdir(parents=True, exist_ok=True)
    if case_path.exists() and not force:
        raise EvalConfigError(f"case YAML already exists: {case_path}")

    video_path = _case_video_path(
        eval_dir=eval_dir,
        case_dir=cases_dir,
        case_name=case_name,
        source_video=source_video,
    )
    if video_path.exists() and not _same_file(source_video, video_path) and not force:
        raise EvalConfigError(f"case video already exists: {video_path}")
    if not _same_file(source_video, video_path):
        shutil.copy2(source_video, video_path)

    case_path.write_text(
        _case_yaml_template(
            video_name=_relative_path(video_path, start=cases_dir),
            target_id=target_id,
            target_label=target_label.strip() if target_label else None,
        ),
        encoding="utf-8",
    )
    return InitCaseResult(
        eval_dir=eval_dir,
        case_path=case_path,
        video_path=video_path,
    )


def _case_video_path(
    *, eval_dir: Path, case_dir: Path, case_name: str, source_video: Path
) -> Path:
    try:
        source_video.relative_to(eval_dir)
    except ValueError:
        return case_dir / f"{case_name}{source_video.suffix.lower()}"
    return source_video


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return False


def _relative_path(path: Path, *, start: Path) -> str:
    return Path(os_path.relpath(path, start=start)).as_posix()


def _case_yaml_template(
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
