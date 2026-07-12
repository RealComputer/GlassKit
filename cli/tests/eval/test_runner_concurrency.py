from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from glasskit.eval.adapters import LoadedEvaluator
from glasskit.eval.models import AdapterRuntimeError, EvalConfigError, RunOptions
from glasskit.eval.runner import run_eval

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EVAL_DIR = FIXTURES / "eval_directories" / "two-state"


def test_runner_defaults_to_serial_individual_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = AsyncTrackingEvaluator()

    report = asyncio.run(_run_with_evaluator(monkeypatch, evaluator))

    assert report.success
    assert evaluator.peak_active == 1
    assert evaluator.completed == [0, 1, 2, 3]
    assert evaluator.closed


def test_runner_bounds_concurrent_evaluation_and_preserves_result_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = AsyncTrackingEvaluator(reverse_completion_order=True)

    report = asyncio.run(_run_with_evaluator(monkeypatch, evaluator, concurrency=3))

    assert report.success
    assert evaluator.peak_active == 3
    assert evaluator.completed != [0, 1, 2, 3]
    assert [result.sample_index for result in report.results] == [0, 1, 2, 3]
    assert evaluator.closed


def test_runner_runs_sync_individual_evaluators_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = SyncTrackingEvaluator()

    report = asyncio.run(_run_with_evaluator(monkeypatch, evaluator, concurrency=3))

    assert report.success
    assert evaluator.peak_active == 3
    assert evaluator.closed


def test_runner_uses_native_batch_instead_of_individual_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = BatchEvaluator()

    report = asyncio.run(
        _run_with_evaluator(monkeypatch, evaluator, concurrency=4, batch=True)
    )

    assert report.success
    assert evaluator.batch_calls == 1
    assert evaluator.batch_sizes == [4]


def test_keep_going_records_only_the_failing_individual_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = OneErrorEvaluator()

    report = asyncio.run(
        _run_with_evaluator(
            monkeypatch,
            evaluator,
            concurrency=3,
            keep_going=True,
        )
    )

    assert [result.status for result in report.results] == [
        "passed",
        "error",
        "passed",
        "passed",
    ]
    assert "case-001/step_1 sample 1 at 0.5s" in report.results[1].reason
    assert evaluator.closed


def test_individual_evaluation_stops_queued_work_and_drains_in_flight_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = FailFastEvaluator()

    with pytest.raises(AdapterRuntimeError, match="sample 0"):
        asyncio.run(_run_with_evaluator(monkeypatch, evaluator, concurrency=2))

    assert evaluator.started == [0, 1]
    assert evaluator.active == 0
    assert evaluator.closed


@pytest.mark.parametrize(
    ("batch", "concurrency", "expected_started"),
    [
        (False, 2, 2),
        (True, 8, 1),
    ],
)
def test_cancellation_drains_sync_calls_before_closing_evaluator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    batch: bool,
    concurrency: int,
    expected_started: int,
) -> None:
    evaluator = CancellationTrackingSyncEvaluator(expected_started=expected_started)

    asyncio.run(
        _cancel_run_while_sync_calls_are_active(
            monkeypatch,
            evaluator,
            batch=batch,
            concurrency=concurrency,
        )
    )

    assert evaluator.completed == expected_started
    assert evaluator.close_active == 0
    assert evaluator.closed


def test_runner_rejects_non_positive_programmatic_concurrency(
    tmp_path: Path,
) -> None:
    with pytest.raises(EvalConfigError, match="concurrency must be greater than 0"):
        asyncio.run(
            run_eval(
                RunOptions(
                    eval_dir=tmp_path,
                    adapter="unused:create_evaluator",
                    concurrency=0,
                )
            )
        )


async def _run_with_evaluator(
    monkeypatch: pytest.MonkeyPatch,
    evaluator: Any,
    *,
    concurrency: int = 1,
    keep_going: bool = False,
    batch: bool = False,
) -> Any:
    loaded = LoadedEvaluator(
        evaluate=getattr(evaluator, "evaluate", None),
        evaluate_many=evaluator.evaluate_many if batch else None,
        close=evaluator.close,
    )

    async def load_evaluator(*args: Any, **kwargs: Any) -> LoadedEvaluator:
        return loaded

    monkeypatch.setattr("glasskit.eval.runner.load_evaluator", load_evaluator)
    return await run_eval(
        RunOptions(
            eval_dir=EVAL_DIR,
            adapter="unused:create_evaluator",
            concurrency=concurrency,
            keep_going=keep_going,
        )
    )


async def _cancel_run_while_sync_calls_are_active(
    monkeypatch: pytest.MonkeyPatch,
    evaluator: CancellationTrackingSyncEvaluator,
    *,
    batch: bool,
    concurrency: int,
) -> None:
    run_task = asyncio.create_task(
        _run_with_evaluator(
            monkeypatch,
            evaluator,
            batch=batch,
            concurrency=concurrency,
        )
    )
    cancelled = False
    try:
        async with asyncio.timeout(1):
            while not evaluator.all_started.is_set():
                await asyncio.sleep(0.005)
        run_task.cancel()
        await asyncio.sleep(0)
        run_task.cancel()
        await asyncio.sleep(0.02)
        assert not run_task.done()
        assert not evaluator.closed
    finally:
        evaluator.release.set()
        if not run_task.done() and run_task.cancelling() == 0:
            run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            cancelled = True
    assert cancelled


def _observation(sample: Any) -> bool:
    return sample.timestamp_s >= 1.0


class AsyncTrackingEvaluator:
    def __init__(self, *, reverse_completion_order: bool = False) -> None:
        self.reverse_completion_order = reverse_completion_order
        self.active = 0
        self.peak_active = 0
        self.completed: list[int] = []
        self.closed = False

    async def evaluate(self, sample: Any, target: Any) -> bool:
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            delay = (
                (4 - sample.sample_index) * 0.005
                if self.reverse_completion_order
                else 0
            )
            await asyncio.sleep(delay)
            self.completed.append(sample.sample_index)
            return _observation(sample)
        finally:
            self.active -= 1

    async def close(self) -> None:
        self.closed = True


class SyncTrackingEvaluator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.peak_active = 0
        self.closed = False

    def evaluate(self, sample: Any, target: Any) -> bool:
        with self._lock:
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
        try:
            time.sleep(0.02)
            return _observation(sample)
        finally:
            with self._lock:
                self.active -= 1

    def close(self) -> None:
        self.closed = True


class BatchEvaluator:
    def __init__(self) -> None:
        self.batch_calls = 0
        self.batch_sizes: list[int] = []

    async def evaluate_many(self, samples: list[Any], target: Any) -> list[bool]:
        self.batch_calls += 1
        self.batch_sizes.append(len(samples))
        return [_observation(sample) for sample in samples]

    async def close(self) -> None:
        return None


class OneErrorEvaluator:
    def __init__(self) -> None:
        self.closed = False

    async def evaluate(self, sample: Any, target: Any) -> bool:
        await asyncio.sleep(0)
        if sample.sample_index == 1:
            raise RuntimeError("provider unavailable")
        return _observation(sample)

    async def close(self) -> None:
        self.closed = True


class FailFastEvaluator:
    def __init__(self) -> None:
        self.started: list[int] = []
        self.active = 0
        self.closed = False

    async def evaluate(self, sample: Any, target: Any) -> bool:
        self.started.append(sample.sample_index)
        self.active += 1
        try:
            if sample.sample_index == 0:
                await asyncio.sleep(0)
                raise RuntimeError("first call failed")
            await asyncio.sleep(0.02)
            return _observation(sample)
        finally:
            self.active -= 1

    async def close(self) -> None:
        self.closed = True


class CancellationTrackingSyncEvaluator:
    def __init__(self, *, expected_started: int) -> None:
        self.expected_started = expected_started
        self.release = threading.Event()
        self.all_started = threading.Event()
        self._lock = threading.Lock()
        self.started = 0
        self.active = 0
        self.completed = 0
        self.close_active: int | None = None
        self.closed = False

    def evaluate(self, sample: Any, target: Any) -> bool:
        self._wait_for_release()
        return _observation(sample)

    def evaluate_many(self, samples: list[Any], target: Any) -> list[bool]:
        self._wait_for_release()
        return [_observation(sample) for sample in samples]

    def close(self) -> None:
        with self._lock:
            self.close_active = self.active
            self.closed = True

    def _wait_for_release(self) -> None:
        with self._lock:
            self.started += 1
            self.active += 1
            if self.started == self.expected_started:
                self.all_started.set()
        try:
            self.release.wait(timeout=5)
        finally:
            with self._lock:
                self.active -= 1
                self.completed += 1
