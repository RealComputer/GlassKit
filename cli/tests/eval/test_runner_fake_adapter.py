from __future__ import annotations

import asyncio
from fractions import Fraction
from pathlib import Path

import av
from PIL import Image

from gk.eval.models import RunOptions
from gk.eval.runner import run_eval


def test_runner_evaluates_synthetic_video_with_fake_adapter(tmp_path: Path) -> None:
    asyncio.run(_run_synthetic_video_test(tmp_path))


def test_runner_applies_suite_level_per_target_gates(tmp_path: Path) -> None:
    asyncio.run(_run_suite_per_target_gate_test(tmp_path))


async def _run_synthetic_video_test(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suite"
    case_dir = suite_dir / "fold-step-001"
    case_dir.mkdir(parents=True)
    video_path = case_dir / "video.mp4"
    _write_video(video_path)
    (case_dir / "expected.yaml").write_text(
        """
version: 1
video: video.mp4
targets:
  step_1:
    samples:
      - range: [0.0, 1.0]
        every_s: 0.5
        expect: false
      - range: [1.0, 2.0]
        every_s: 0.5
        expect: true
thresholds:
  min_pass_rate: 1.0
        """,
        encoding="utf-8",
    )
    adapter_path = tmp_path / "fake_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        return [sample.timestamp_s >= 1.0 for sample in samples]

    async def evaluate(self, sample, target):
        return sample.timestamp_s >= 1.0

    async def close(self):
        return None

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )

    report = await run_eval(
        RunOptions(
            suite_path=suite_dir,
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    assert report.success
    assert report.evaluated_count == 4
    assert report.passed_count == 4


async def _run_suite_per_target_gate_test(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suite"
    case_dir = suite_dir / "case-001"
    case_dir.mkdir(parents=True)
    _write_video(case_dir / "video.mp4")
    (suite_dir / "suite.yaml").write_text(
        """
thresholds:
  per_target:
    step_2:
      min_pass_rate: 1.0
        """,
        encoding="utf-8",
    )
    (case_dir / "expected.yaml").write_text(
        """
version: 1
video: video.mp4
targets:
  step_1:
    samples:
      - at: 0.0
        expect: true
  step_2:
    samples:
      - at: 0.0
        expect: true
        """,
        encoding="utf-8",
    )
    adapter_path = tmp_path / "fake_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        return [target.id == "step_1" for sample in samples]

    async def evaluate(self, sample, target):
        return target.id == "step_1"

    async def close(self):
        return None

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )

    report = await run_eval(
        RunOptions(
            suite_path=suite_dir,
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    gate = next(
        gate
        for gate in report.gate_results
        if gate.name == "suite_step_2_min_pass_rate"
    )
    assert not gate.passed
    assert not report.success


def _write_video(path: Path, *, fps: int = 4, frames: int = 8) -> None:
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width = 64
        stream.height = 64
        stream.pix_fmt = "yuv420p"
        for index in range(frames):
            color = "black" if index < frames // 2 else "white"
            image = Image.new("RGB", (64, 64), color)
            frame = av.VideoFrame.from_image(image)
            frame.pts = index
            frame.time_base = Fraction(1, fps)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
