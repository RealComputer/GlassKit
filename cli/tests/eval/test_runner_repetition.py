from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from glasskit.eval.adapters import LoadedEvaluator
from glasskit.eval.models import EvalConfigError, RunOptions
from glasskit.eval.runner import run_eval

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TWO_STATE_EVAL = FIXTURES / "eval_directories" / "two-state"
TWO_STATE_VIDEO = FIXTURES / "videos" / "two-state-64x64.mp4"


def test_runner_repeats_with_fresh_sequential_evaluators_and_reports_stability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_run_varying_trials(tmp_path, monkeypatch))


def test_runner_names_repeated_failure_artifacts_without_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_run_repeated_failure_artifacts(tmp_path, monkeypatch))


@pytest.mark.parametrize(
    ("repeat", "max_flaky_samples", "message"),
    [
        (0, None, "repeat must be greater than 0"),
        (
            1,
            0,
            "--max-flaky-samples requires --repeat to be at least 2",
        ),
        (
            2,
            -1,
            "max flaky samples must be nonnegative",
        ),
    ],
)
def test_runner_validates_repetition_options(
    tmp_path: Path,
    repeat: int,
    max_flaky_samples: int | None,
    message: str,
) -> None:
    with pytest.raises(EvalConfigError, match=message):
        asyncio.run(
            run_eval(
                RunOptions(
                    eval_dir=tmp_path,
                    adapter="unused:create_evaluator",
                    repeat=repeat,
                    max_flaky_samples=max_flaky_samples,
                )
            )
        )


async def _run_varying_trials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lifecycle = _Lifecycle()
    monkeypatch.setattr("glasskit.eval.execution.load_evaluator", lifecycle.load)
    output_json = tmp_path / "repeated.json"

    report = await run_eval(
        RunOptions(
            eval_dir=TWO_STATE_EVAL,
            adapter="unused:create_evaluator",
            concurrency=2,
            repeat=3,
            max_flaky_samples=0,
            output_json=output_json,
        )
    )

    assert lifecycle.created == [1, 2, 3]
    assert lifecycle.closed == [1, 2, 3]
    assert lifecycle.active_trial is None
    assert [trial.index for trial in report.trials] == [1, 2, 3]
    assert [trial.success for trial in report.trials] == [True, False, True]
    assert report.successful_trial_count == 2
    assert report.evaluated_sample_count == 4
    assert report.evaluated_attempt_count == 12
    assert report.passed_attempt_count == 11
    assert report.flaky_sample_count == 1
    assert report.consistently_passed_sample_count == 3
    assert report.stability[0].statuses == ("passed", "failed", "passed")
    assert report.stability[0].pass_rate == pytest.approx(2 / 3)
    assert report.stability[0].flaky
    assert not report.success
    assert report.gate_results[0].name == "max_flaky_samples"
    assert not report.gate_results[0].passed

    written = json.loads(output_json.read_text(encoding="utf-8"))
    assert written["schema_version"] == 1
    assert written["report_type"] == "eval_run"
    assert written["repeat_count"] == 3
    assert written["summary"]["flaky_samples"] == 1
    assert [trial["success"] for trial in written["trials"]] == [True, False, True]
    assert written["stability"][0]["statuses"] == ["passed", "failed", "passed"]


async def _run_repeated_failure_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir = _write_single_sample_eval(tmp_path)
    evaluators: list[_AlwaysFalseEvaluator] = []

    async def load_evaluator(*args: Any, **kwargs: Any) -> LoadedEvaluator:
        evaluator = _AlwaysFalseEvaluator()
        evaluators.append(evaluator)
        return LoadedEvaluator(
            evaluate=evaluator.evaluate,
            evaluate_many=None,
            close=evaluator.close,
        )

    monkeypatch.setattr("glasskit.eval.execution.load_evaluator", load_evaluator)

    report = await run_eval(
        RunOptions(
            eval_dir=eval_dir,
            adapter="unused:create_evaluator",
            repeat=2,
            max_flaky_samples=0,
            save_failures=True,
            artifacts_dir=tmp_path / "artifacts",
        )
    )

    results = [trial.results[0] for trial in report.trials]
    image_paths = [Path(result.artifact_image or "") for result in results]
    json_paths = [Path(result.artifact_json or "") for result in results]
    assert all(evaluator.closed for evaluator in evaluators)
    assert len(set(image_paths)) == 2
    assert len(set(json_paths)) == 2
    assert image_paths[0].parent.name == "trial-001"
    assert image_paths[1].parent.name == "trial-002"
    assert all(path.exists() for path in [*image_paths, *json_paths])
    assert json.loads(json_paths[0].read_text(encoding="utf-8"))["trial"] == 1
    assert json.loads(json_paths[1].read_text(encoding="utf-8"))["trial"] == 2
    assert report.stability[0].statuses == ("failed", "failed")
    assert report.stability[0].consistently_failed
    assert not report.stability[0].flaky
    assert report.gate_results[0].passed
    assert report.success


def _write_single_sample_eval(tmp_path: Path) -> Path:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case.yaml").write_text(
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
    return eval_dir


class _Lifecycle:
    def __init__(self) -> None:
        self.created: list[int] = []
        self.closed: list[int] = []
        self.active_trial: int | None = None

    async def load(self, *args: Any, **kwargs: Any) -> LoadedEvaluator:
        assert self.active_trial is None
        trial_index = len(self.created) + 1
        self.created.append(trial_index)
        self.active_trial = trial_index
        evaluator = _VaryingEvaluator(trial_index, self)
        return LoadedEvaluator(
            evaluate=evaluator.evaluate,
            evaluate_many=None,
            close=evaluator.close,
        )


class _VaryingEvaluator:
    def __init__(self, trial_index: int, lifecycle: _Lifecycle) -> None:
        self.trial_index = trial_index
        self.lifecycle = lifecycle

    async def evaluate(self, sample: Any, target: Any) -> bool:
        observation = sample.timestamp_s >= 1.0
        if self.trial_index == 2 and sample.sample_index == 0:
            return not observation
        return observation

    async def close(self) -> None:
        assert self.lifecycle.active_trial == self.trial_index
        self.lifecycle.closed.append(self.trial_index)
        self.lifecycle.active_trial = None


class _AlwaysFalseEvaluator:
    def __init__(self) -> None:
        self.closed = False

    async def evaluate(self, sample: Any, target: Any) -> bool:
        return False

    async def close(self) -> None:
        self.closed = True
