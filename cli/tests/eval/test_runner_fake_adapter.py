from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from gk.eval.models import AdapterRuntimeError, RunOptions
from gk.eval.runner import run_eval

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TWO_STATE_VIDEO = (FIXTURES / "videos" / "two-state-64x64.mp4").as_posix()


def test_runner_evaluates_committed_fixture_with_fake_adapter(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_committed_fixture_test(tmp_path))


def test_runner_saves_failure_artifacts_for_committed_fixture(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_committed_fixture_artifact_test(tmp_path))


def test_runner_applies_suite_level_per_target_gates(tmp_path: Path) -> None:
    asyncio.run(_run_suite_per_target_gate_test(tmp_path))


def test_runner_skips_filtered_out_suite_target_gates(tmp_path: Path) -> None:
    asyncio.run(_run_filtered_suite_target_gate_test(tmp_path))


def test_runner_records_non_json_adapter_observations_with_keep_going(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_non_json_adapter_observation_test(tmp_path))


def test_runner_preserves_eval_error_when_close_also_fails(tmp_path: Path) -> None:
    asyncio.run(_run_close_error_masking_test(tmp_path))


async def _run_committed_fixture_test(tmp_path: Path) -> None:
    suite_dir = FIXTURES / "eval_suites" / "two-state"
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


async def _run_committed_fixture_artifact_test(tmp_path: Path) -> None:
    suite_dir = FIXTURES / "eval_suites" / "two-state"
    adapter_path = tmp_path / "fake_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        return [False for sample in samples]

    async def evaluate(self, sample, target):
        return False

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
            artifacts_dir=tmp_path / "artifacts",
            save_failures=True,
        )
    )

    failed = [result for result in report.results if result.status == "failed"]
    assert not report.success
    assert len(failed) == 2
    for result in failed:
        assert result.artifact_image is not None
        assert result.artifact_json is not None
        assert Path(result.artifact_image).exists()
        assert Path(result.artifact_json).exists()


async def _run_suite_per_target_gate_test(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suite"
    case_dir = suite_dir / "case-001"
    case_dir.mkdir(parents=True)
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
        f"""
version: 1
video: "{TWO_STATE_VIDEO}"
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


async def _run_filtered_suite_target_gate_test(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suite"
    case_1 = suite_dir / "case-001"
    case_2 = suite_dir / "case-002"
    case_1.mkdir(parents=True)
    case_2.mkdir(parents=True)
    (suite_dir / "suite.yaml").write_text(
        """
thresholds:
  per_target:
    step_1:
      min_pass_rate: 1.0
    step_2:
      min_pass_rate: 1.0
        """,
        encoding="utf-8",
    )
    (case_1 / "expected.yaml").write_text(
        f"""
version: 1
video: "{TWO_STATE_VIDEO}"
targets:
  step_1:
    samples:
      - at: 0.0
        expect: true
        """,
        encoding="utf-8",
    )
    (case_2 / "expected.yaml").write_text(
        f"""
version: 1
video: "{TWO_STATE_VIDEO}"
targets:
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
        return [True for sample in samples]

    async def evaluate(self, sample, target):
        return True

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
            case_filter="case-001",
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    gate_names = {gate.name for gate in report.gate_results}
    assert "suite_step_1_min_pass_rate" in gate_names
    assert "suite_step_2_min_pass_rate" not in gate_names
    assert report.success


async def _run_non_json_adapter_observation_test(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suite"
    case_dir = suite_dir / "case-001"
    case_dir.mkdir(parents=True)
    (case_dir / "expected.yaml").write_text(
        f"""
version: 1
video: "{TWO_STATE_VIDEO}"
targets:
  step_1:
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
        return [object() for sample in samples]

    async def evaluate(self, sample, target):
        return object()

    async def close(self):
        return None

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )
    output_json = tmp_path / "report.json"

    report = await run_eval(
        RunOptions(
            suite_path=suite_dir,
            adapter=f"{adapter_path}:create_evaluator",
            keep_going=True,
            output_json=output_json,
        )
    )

    assert report.error_count == 1
    assert output_json.exists()
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["results"][0]["status"] == "error"
    assert "non-JSON observation" in data["results"][0]["reason"]


async def _run_close_error_masking_test(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suite"
    case_dir = suite_dir / "case-001"
    case_dir.mkdir(parents=True)
    (case_dir / "expected.yaml").write_text(
        f"""
version: 1
video: "{TWO_STATE_VIDEO}"
targets:
  step_1:
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
        raise RuntimeError("evaluation failed")

    async def evaluate(self, sample, target):
        raise RuntimeError("evaluation failed")

    async def close(self):
        raise RuntimeError("close failed")

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )

    with pytest.raises(AdapterRuntimeError, match="evaluation failed") as exc_info:
        await run_eval(
            RunOptions(
                suite_path=suite_dir,
                adapter=f"{adapter_path}:create_evaluator",
            )
        )
    assert "close failed" not in str(exc_info.value)
    assert any("close failed" in note for note in exc_info.value.__notes__)
