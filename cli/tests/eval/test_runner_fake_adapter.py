from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from glasskit.eval.models import AdapterRuntimeError, RunOptions
from glasskit.eval.runner import run_eval

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


def test_runner_saves_individual_failure_artifacts_while_frames_are_live(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_individual_failure_artifact_test(tmp_path))


def test_runner_saves_failure_artifacts_in_eval_runs_by_default(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_default_failure_artifact_dir_test(tmp_path))


def test_runner_applies_eval_directory_level_per_target_gates(tmp_path: Path) -> None:
    asyncio.run(_run_eval_directory_per_target_gate_test(tmp_path))


def test_runner_keeps_missing_case_target_gate_on_unfiltered_run(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_missing_case_target_gate_test(tmp_path))


def test_runner_skips_filtered_out_eval_directory_target_gates(tmp_path: Path) -> None:
    asyncio.run(_run_filtered_eval_directory_target_gate_test(tmp_path))


def test_runner_filters_by_target_without_case(tmp_path: Path) -> None:
    asyncio.run(_run_target_filter_without_case_test(tmp_path))


def test_runner_filters_multiple_targets_and_time_window_gates(tmp_path: Path) -> None:
    asyncio.run(_run_multiple_target_filter_test(tmp_path))


def test_runner_filters_adapter_input_and_gates_by_time_window(tmp_path: Path) -> None:
    asyncio.run(_run_time_window_filter_test(tmp_path))


def test_runner_records_non_json_adapter_observations_with_keep_going(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_non_json_adapter_observation_test(tmp_path))


def test_runner_records_duration_in_report_and_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_run_duration_report_test(tmp_path, monkeypatch))


def test_runner_preserves_eval_error_when_close_also_fails(tmp_path: Path) -> None:
    asyncio.run(_run_close_error_masking_test(tmp_path))


def test_runner_handles_malformed_evaluate_many_return(tmp_path: Path) -> None:
    asyncio.run(_run_malformed_evaluate_many_return_test(tmp_path))


def test_runner_reports_ignored_samples_without_evaluating_or_scoring_them(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_ignored_sample_test(tmp_path))


async def _run_committed_fixture_test(tmp_path: Path) -> None:
    eval_dir = FIXTURES / "eval_directories" / "two-state"
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
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    assert report.success
    assert report.trials[0].evaluated_count == 4
    assert report.trials[0].passed_count == 4


async def _run_time_window_filter_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case-001.yaml").write_text(
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  early:
    samples:
      - at: 0.0
        expect: true
  late:
    samples:
      - at: [0.5, 1.0, 1.5]
        expect: true
thresholds:
  per_target:
    early:
      min_pass_rate: 1.0
    late:
      min_pass_rate: 1.0
    misspelled:
      min_pass_rate: 1.0
        """,
        encoding="utf-8",
    )
    adapter_path = tmp_path / "fake_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        if target.id != "late":
            raise RuntimeError("time-filtered target reached the adapter")
        if [sample.timestamp_s for sample in samples] != [1.0]:
            raise RuntimeError("unexpected time-filtered batch")
        return [True]

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )

    report = await run_eval(
        RunOptions(
            eval_dir=eval_dir,
            case_filter="case-001",
            from_time_s=1.0,
            until_time_s=1.5,
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    results = report.trials[0].results
    assert [result.target_id for result in results] == ["late"]
    assert [result.timestamp_s for result in results] == [1.0]
    assert [result.sample_index for result in results] == [2]
    gate_names = {gate.name for gate in report.trials[0].gate_results}
    assert "case-001_early_min_pass_rate" not in gate_names
    assert "case-001_late_min_pass_rate" in gate_names
    missing_gate = next(
        gate
        for gate in report.trials[0].gate_results
        if gate.name == "case-001_misspelled_min_pass_rate"
    )
    assert not missing_gate.passed
    assert not report.success


async def _run_ignored_sample_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case-001.yaml").write_text(
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  step_1:
    samples:
      - at: 0.0
        expect: false
        ignore: Provider output is flaky for this difficult frame.
      - at: 1.0
        expect: true
thresholds:
  min_pass_rate: 1.0
  max_failures: 0
        """,
        encoding="utf-8",
    )
    adapter_path = tmp_path / "fake_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        if [sample.timestamp_s for sample in samples] != [1.0]:
            raise RuntimeError("ignored sample reached the adapter")
        return [True]

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )
    output_path = tmp_path / "report.json"

    report = await run_eval(
        RunOptions(
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
            output_json=output_path,
        )
    )

    assert report.success
    results = report.trials[0].results
    assert [result.status for result in results] == ["ignored", "passed"]
    assert results[0].reason == ("Provider output is flaky for this difficult frame.")
    assert results[0].evaluation_duration_s is None
    assert report.trials[0].evaluated_count == 1
    assert report.trials[0].ignored_count == 1
    assert report.trials[0].pass_rate == 1.0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["summary"]["evaluated_samples"] == 1
    assert written["summary"]["ignored_samples"] == 1
    assert [result["status"] for result in written["trials"][0]["results"]] == [
        "ignored",
        "passed",
    ]


async def _run_committed_fixture_artifact_test(tmp_path: Path) -> None:
    eval_dir = FIXTURES / "eval_directories" / "two-state"
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
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
            artifacts_dir=tmp_path / "artifacts",
            save_failures=True,
        )
    )

    failed = [
        result for result in report.trials[0].results if result.status == "failed"
    ]
    assert not report.success
    assert len(failed) == 2
    for result in failed:
        assert result.artifact_image is not None
        assert result.artifact_json is not None
        assert result.evaluation_duration_s is not None
        assert result.evaluation_timing_mode == "batch_amortized"
        assert Path(result.artifact_image).exists()
        assert Path(result.artifact_json).exists()


async def _run_individual_failure_artifact_test(tmp_path: Path) -> None:
    eval_dir = FIXTURES / "eval_directories" / "two-state"
    adapter_path = tmp_path / "individual_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
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
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
            artifacts_dir=tmp_path / "artifacts",
            save_failures=True,
            concurrency=2,
        )
    )

    failed = [
        result for result in report.trials[0].results if result.status == "failed"
    ]
    assert len(failed) == 2
    for result in failed:
        assert result.artifact_image is not None
        assert result.artifact_json is not None
        assert result.evaluation_timing_mode == "individual"
        assert Path(result.artifact_image).exists()
        assert Path(result.artifact_json).exists()


async def _run_default_failure_artifact_dir_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case-001.yaml").write_text(
        f"""
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
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
            save_failures=True,
        )
    )

    assert report.trials[0].failed_count == 1
    result = report.trials[0].results[0]
    assert result.artifact_image is not None
    assert result.artifact_json is not None
    expected_dir = eval_dir / "runs" / "failures" / "trial-001"
    assert Path(result.artifact_image).parent == expected_dir
    assert Path(result.artifact_json).parent == expected_dir
    assert Path(result.artifact_image).exists()
    assert Path(result.artifact_json).exists()


async def _run_eval_directory_per_target_gate_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (eval_dir / "config.yaml").write_text(
        """
thresholds:
  per_target:
    step_2:
      min_pass_rate: 1.0
        """,
        encoding="utf-8",
    )
    (cases_dir / "case-001.yaml").write_text(
        f"""
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
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    gate = next(
        gate
        for gate in report.trials[0].gate_results
        if gate.name == "eval_step_2_min_pass_rate"
    )
    assert not gate.passed
    assert not report.success


async def _run_missing_case_target_gate_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case-001.yaml").write_text(
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  step_1:
    samples:
      - at: 0.0
        expect: true
thresholds:
  per_target:
    misspelled:
      min_pass_rate: 1.0
        """,
        encoding="utf-8",
    )
    adapter_path = tmp_path / "fake_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        return [True for sample in samples]

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )

    report = await run_eval(
        RunOptions(
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    gate = next(
        gate
        for gate in report.trials[0].gate_results
        if gate.name == "case-001_misspelled_min_pass_rate"
    )
    assert not gate.passed
    assert not report.success


async def _run_filtered_eval_directory_target_gate_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (eval_dir / "config.yaml").write_text(
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
    (cases_dir / "case-001.yaml").write_text(
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  step_1:
    samples:
      - at: 0.0
        expect: true
        """,
        encoding="utf-8",
    )
    (cases_dir / "case-002.yaml").write_text(
        f"""
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
            eval_dir=eval_dir,
            case_filter="case-001",
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    gate_names = {gate.name for gate in report.trials[0].gate_results}
    assert "eval_step_1_min_pass_rate" in gate_names
    assert "eval_step_2_min_pass_rate" not in gate_names
    assert report.success


async def _run_target_filter_without_case_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (eval_dir / "config.yaml").write_text(
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
    (cases_dir / "case-001.yaml").write_text(
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  step_1:
    samples:
      - at: 0.0
        expect: true
        """,
        encoding="utf-8",
    )
    (cases_dir / "case-002.yaml").write_text(
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  step_2:
    samples:
      - at: 1.0
        expect: true
        """,
        encoding="utf-8",
    )
    adapter_path = tmp_path / "fake_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        return [target.id == "step_2" for sample in samples]

    async def evaluate(self, sample, target):
        return target.id == "step_2"

    async def close(self):
        return None

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )

    report = await run_eval(
        RunOptions(
            eval_dir=eval_dir,
            target_filter="step_2",
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    gate_names = {gate.name for gate in report.trials[0].gate_results}
    assert report.case_names == ["case-002"]
    assert [result.target_id for result in report.trials[0].results] == ["step_2"]
    assert "eval_step_1_min_pass_rate" not in gate_names
    assert "eval_step_2_min_pass_rate" in gate_names
    assert report.success


async def _run_multiple_target_filter_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (eval_dir / "config.yaml").write_text(
        """
thresholds:
  per_target:
    step_1:
      min_pass_rate: 1.0
    step_2:
      min_pass_rate: 1.0
    step_3:
      min_pass_rate: 1.0
        """,
        encoding="utf-8",
    )
    (cases_dir / "case-001.yaml").write_text(
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  step_1:
    samples:
      - at: 0.0
        expect: true
  step_2:
    samples:
      - at: 1.0
        expect: true
  step_3:
    samples:
      - at: 0.0
        expect: true
thresholds:
  per_target:
    step_1:
      min_pass_rate: 1.0
    step_2:
      min_pass_rate: 1.0
    step_3:
      min_pass_rate: 1.0
        """,
        encoding="utf-8",
    )
    adapter_path = tmp_path / "fake_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        return [target.id in {"step_1", "step_2"} for sample in samples]

    async def evaluate(self, sample, target):
        return target.id in {"step_1", "step_2"}

    async def close(self):
        return None

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )

    report = await run_eval(
        RunOptions(
            eval_dir=eval_dir,
            target_filter=("step_2", "step_1"),
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    gate_names = {gate.name for gate in report.trials[0].gate_results}
    assert [result.target_id for result in report.trials[0].results] == [
        "step_1",
        "step_2",
    ]
    assert "eval_step_1_min_pass_rate" in gate_names
    assert "eval_step_2_min_pass_rate" in gate_names
    assert "eval_step_3_min_pass_rate" not in gate_names
    assert "case-001_step_1_min_pass_rate" in gate_names
    assert "case-001_step_2_min_pass_rate" in gate_names
    assert "case-001_step_3_min_pass_rate" not in gate_names
    assert report.success

    windowed_report = await run_eval(
        RunOptions(
            eval_dir=eval_dir,
            case_filter="case-001",
            target_filter=("step_1", "step_2"),
            from_time_s=0.5,
            until_time_s=1.5,
            adapter=f"{adapter_path}:create_evaluator",
        )
    )

    windowed_gate_names = {gate.name for gate in windowed_report.trials[0].gate_results}
    assert [result.target_id for result in windowed_report.trials[0].results] == [
        "step_2"
    ]
    assert "eval_step_1_min_pass_rate" not in windowed_gate_names
    assert "eval_step_2_min_pass_rate" in windowed_gate_names
    assert "case-001_step_1_min_pass_rate" not in windowed_gate_names
    assert "case-001_step_2_min_pass_rate" in windowed_gate_names
    assert windowed_report.success


async def _run_non_json_adapter_observation_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case-001.yaml").write_text(
        f"""
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
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
            keep_going=True,
            output_json=output_json,
        )
    )

    assert report.trials[0].error_count == 1
    assert output_json.exists()
    data = json.loads(output_json.read_text(encoding="utf-8"))
    result_data = data["trials"][0]["results"][0]
    assert result_data["status"] == "error"
    assert "non-JSON observation" in result_data["reason"]


async def _run_duration_report_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir = FIXTURES / "eval_directories" / "two-state"
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
    output_json = tmp_path / "report.json"
    clock_values = iter([10.0, 20.0, 30.0, 40.0, 72.25, 72.25])

    def clock() -> float:
        return next(clock_values)

    monkeypatch.setattr("glasskit.eval.runner.perf_counter", clock)
    monkeypatch.setattr("glasskit.eval.execution.perf_counter", clock)

    report = await run_eval(
        RunOptions(
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
            output_json=output_json,
        )
    )

    assert report.duration_s == pytest.approx(62.25)
    assert report.evaluation_timing_mode == "batch_amortized"
    assert report.average_evaluation_duration_s == pytest.approx(2.5)
    assert report.throughput_attempts_per_s == pytest.approx(4 / 62.25)
    assert [result.evaluation_duration_s for result in report.trials[0].results] == [
        pytest.approx(2.5)
    ] * 4
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["checkpoint"]["path"] == str(report.checkpoint_path)
    assert not data["checkpoint"]["resumed"]
    assert data["checkpoint"]["resumable_adapter_errors"] == 0
    assert data["summary"]["duration_seconds"] == pytest.approx(62.25)
    assert data["summary"]["evaluation_timing_mode"] == "batch_amortized"
    assert data["summary"]["average_evaluation_seconds_per_attempt"] == pytest.approx(
        2.5
    )
    assert data["summary"]["throughput_attempts_per_second"] == pytest.approx(4 / 62.25)
    result_data = data["trials"][0]["results"][0]
    assert result_data["evaluation_timing_mode"] == "batch_amortized"
    assert result_data["evaluation_duration_seconds"] == pytest.approx(2.5)


async def _run_close_error_masking_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case-001.yaml").write_text(
        f"""
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
                eval_dir=eval_dir,
                adapter=f"{adapter_path}:create_evaluator",
            )
        )
    assert "close failed" not in str(exc_info.value)
    assert any("close failed" in note for note in exc_info.value.__notes__)


async def _run_malformed_evaluate_many_return_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case-001.yaml").write_text(
        f"""
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
        return None

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
            eval_dir=eval_dir,
            adapter=f"{adapter_path}:create_evaluator",
            keep_going=True,
        )
    )

    result = report.trials[0].results[0]
    assert report.trials[0].error_count == 1
    assert result.status == "error"
    assert result.evaluation_duration_s is not None
    assert result.evaluation_timing_mode == "batch_amortized"
    assert "adapter failed for target 'step_1'" in result.reason

    with pytest.raises(AdapterRuntimeError, match="adapter failed for target 'step_1'"):
        await run_eval(
            RunOptions(
                eval_dir=eval_dir,
                adapter=f"{adapter_path}:create_evaluator",
            )
        )
