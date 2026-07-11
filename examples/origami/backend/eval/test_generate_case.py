from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from eval.generate_case import (
    GeminiResult,
    LabelPlan,
    SampleRequest,
    TargetPlan,
    TargetRange,
    _load_existing_case_for_target_update,
    _write_case_yaml,
)


class WriteCaseYamlTests(unittest.TestCase):
    def test_target_update_preserves_other_targets_and_case_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_path = root / "video.mp4"
            video_path.touch()
            output_path = root / "case.yaml"
            output_path.write_text(
                """video: video.mp4
description: Reviewed description
sampling:
  every_s: 0.5
reviewer: human
targets:
  step_1:
    samples:
    - at: 0.0
      expect: true
  step_2:
    label: Keep me
    samples:
    - at: 1.0
      expect: true
""",
                encoding="utf-8",
            )
            output_path.chmod(0o640)
            plan, requests, results = _generation_inputs(video_path)
            existing_case = _load_existing_case_for_target_update(
                output_path,
                plan=plan,
            )

            _write_case_yaml(
                output_path,
                plan=plan,
                requests_by_target=requests,
                results=results,
                existing_case=existing_case,
            )

            written = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["description"], "Reviewed description")
            self.assertEqual(written["reviewer"], "human")
            self.assertEqual(
                written["targets"]["step_1"]["samples"],
                [{"at": 0.0, "expect": False}],
            )
            self.assertEqual(
                written["targets"]["step_2"],
                {
                    "label": "Keep me",
                    "samples": [{"at": 1.0, "expect": True}],
                },
            )
            self.assertEqual(output_path.stat().st_mode & 0o777, 0o640)

    def test_full_generation_overwrites_existing_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_path = root / "video.mp4"
            video_path.touch()
            output_path = root / "case.yaml"
            output_path.write_text(
                "video: old.mp4\ntargets:\n  old_target: {}\n",
                encoding="utf-8",
            )
            plan, requests, results = _generation_inputs(video_path)

            _write_case_yaml(
                output_path,
                plan=plan,
                requests_by_target=requests,
                results=results,
                existing_case=None,
            )

            written = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["video"], "video.mp4")
            self.assertEqual(written["description"], "Generated description")
            self.assertEqual(written["sampling"], {"every_s": 0.5})
            self.assertEqual(list(written["targets"]), ["step_1"])


def _generation_inputs(
    video_path: Path,
) -> tuple[
    LabelPlan,
    dict[str, list[SampleRequest]],
    dict[str, GeminiResult],
]:
    target = TargetPlan(
        id="step_1",
        label=None,
        ranges=[TargetRange(start_s=0.0, end_s=0.5)],
    )
    plan = LabelPlan(
        path=video_path.parent / "plan.yaml",
        video_path=video_path,
        description="Generated description",
        every_s=0.5,
        targets=[target],
    )
    request = SampleRequest(
        target_id="step_1",
        timestamp_s=0.0,
        interval_end_s=0.5,
        next_grid_timestamp_s=0.5,
        cache_key="sample-key",
    )
    return (
        plan,
        {"step_1": [request]},
        {
            "sample-key": GeminiResult(
                value=False,
                response_text="false",
                interaction_id=None,
            )
        },
    )


if __name__ == "__main__":
    unittest.main()
