from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from glasskit.eval.adapters import LoadedEvaluator
from glasskit.eval.models import (
    AdapterRuntimeError,
    EvalConfigError,
    FrameSample,
    RunOptions,
)
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
    assert report.evaluation_timing_mode == "individual"
    assert report.average_evaluation_duration_s is not None
    assert report.average_evaluation_duration_s > 0
    assert all(
        result.evaluation_timing_mode == "individual"
        and result.evaluation_duration_s is not None
        for result in report.results
    )
    assert evaluator.closed


def test_runner_runs_sync_individual_evaluators_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = SyncTrackingEvaluator()

    report = asyncio.run(_run_with_evaluator(monkeypatch, evaluator, concurrency=3))

    assert report.success
    assert evaluator.peak_active == 3
    assert evaluator.closed


def test_runner_decodes_only_concurrent_individual_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_individual_frame_decoding_is_bounded(monkeypatch))


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


def test_runner_buffers_only_the_current_batch_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_assert_batch_frame_decoding_is_target_bounded(tmp_path, monkeypatch))


def test_runner_handles_targets_declared_out_of_timestamp_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir = _write_eval(
        tmp_path,
        """
  later:
    samples:
      - at: 1.0
        expect: true
  earlier:
    samples:
      - at: 0.0
        expect: false
        """,
    )
    evaluator = AsyncTrackingEvaluator()

    report = asyncio.run(_run_with_evaluator(monkeypatch, evaluator, eval_dir=eval_dir))

    assert report.success
    assert evaluator.completed == [0, 1]
    assert [result.target_id for result in report.results] == ["later", "earlier"]


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
    assert report.results[1].evaluation_timing_mode == "individual"
    assert report.results[1].evaluation_duration_s is not None
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


def test_cancellation_skips_sync_calls_still_queued_in_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = QueuedCancellationSyncEvaluator()

    asyncio.run(_cancel_run_with_saturated_executor(monkeypatch, evaluator))

    assert evaluator.started == 0
    assert evaluator.closed


def test_repeated_cancellation_still_runs_queued_sync_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = QueuedCloseSyncEvaluator()

    asyncio.run(_cancel_run_while_sync_close_is_queued(monkeypatch, evaluator))

    assert evaluator.closed


def test_cancellation_preserves_every_sync_drain_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = CancellationFailureSyncEvaluator(expected_started=3)

    cancellation = asyncio.run(
        _cancel_run_while_sync_calls_are_active(
            monkeypatch,
            evaluator,
            batch=False,
            concurrency=3,
        )
    )

    notes = cancellation.__notes__
    assert len(notes) == 3
    for sample_index in range(3):
        assert any(f"provider failure {sample_index}" in note for note in notes)
    assert evaluator.completed == 3
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
    eval_dir: Path = EVAL_DIR,
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
            eval_dir=eval_dir,
            adapter="unused:create_evaluator",
            concurrency=concurrency,
            keep_going=keep_going,
        )
    )


async def _assert_individual_frame_decoding_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = BlockingAsyncEvaluator(expected_started=2)
    decoded: list[int] = []
    monkeypatch.setattr(
        "glasskit.eval.runner.iter_sample_frames", _tracked_frames(decoded)
    )
    run_task = asyncio.create_task(
        _run_with_evaluator(monkeypatch, evaluator, concurrency=2)
    )
    try:
        async with asyncio.timeout(1):
            await evaluator.all_started.wait()
        assert decoded == [0, 1]
    finally:
        evaluator.release.set()

    report = await run_task

    assert report.success
    assert decoded == [0, 1, 2, 3]
    assert evaluator.peak_active == 2


async def _assert_batch_frame_decoding_is_target_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir = _write_eval(
        tmp_path,
        """
  first:
    samples:
      - at: [0.0, 0.5]
        expect: false
  second:
    samples:
      - at: [1.0, 1.5]
        expect: true
        """,
    )
    evaluator = BlockingBatchEvaluator()
    decoded: list[int] = []
    monkeypatch.setattr(
        "glasskit.eval.runner.iter_sample_frames", _tracked_frames(decoded)
    )
    run_task = asyncio.create_task(
        _run_with_evaluator(monkeypatch, evaluator, eval_dir=eval_dir, batch=True)
    )
    try:
        async with asyncio.timeout(1):
            await evaluator.first_batch_started.wait()
        assert decoded == [0, 1]
        assert evaluator.targets == ["first"]
    finally:
        evaluator.release.set()

    report = await run_task

    assert report.success
    assert decoded == [0, 1, 2, 3]
    assert evaluator.targets == ["first", "second"]


def _tracked_frames(decoded: list[int]):
    def iter_frames(video_path: Path, samples: list[Any], *, case_name: str):
        for sample in sorted(
            samples, key=lambda item: (item.timestamp_s, item.sample_index)
        ):
            decoded.append(sample.sample_index)
            yield FrameSample(
                image=Image.new("RGB", (2, 2), "white"),
                timestamp_s=sample.timestamp_s,
                frame_index=sample.sample_index,
                sample_index=sample.sample_index,
                video_path=str(video_path),
                case_name=case_name,
            )

    return iter_frames


def _write_eval(tmp_path: Path, targets: str) -> Path:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    video_path = FIXTURES / "videos" / "two-state-64x64.mp4"
    (cases_dir / "case.yaml").write_text(
        f'video: "{video_path}"\ntargets:\n{targets}',
        encoding="utf-8",
    )
    return eval_dir


async def _cancel_run_while_sync_calls_are_active(
    monkeypatch: pytest.MonkeyPatch,
    evaluator: CancellationTrackingSyncEvaluator,
    *,
    batch: bool,
    concurrency: int,
) -> asyncio.CancelledError:
    run_task = asyncio.create_task(
        _run_with_evaluator(
            monkeypatch,
            evaluator,
            batch=batch,
            concurrency=concurrency,
        )
    )
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
        except asyncio.CancelledError as cancellation:
            return cancellation
    raise AssertionError("eval run did not propagate cancellation")


async def _cancel_run_with_saturated_executor(
    monkeypatch: pytest.MonkeyPatch,
    evaluator: QueuedCancellationSyncEvaluator,
) -> None:
    loop = asyncio.get_running_loop()
    executor = SubmissionTrackingExecutor(max_workers=1)
    loop.set_default_executor(executor)
    blocker_release = threading.Event()
    blocker_started = threading.Event()

    def occupy_only_worker() -> None:
        blocker_started.set()
        blocker_release.wait(timeout=5)

    blocker = loop.run_in_executor(None, occupy_only_worker)
    run_task: asyncio.Task[Any] | None = None
    try:
        async with asyncio.timeout(1):
            while not blocker_started.is_set():
                await asyncio.sleep(0.005)
        run_task = asyncio.create_task(
            _run_with_evaluator(monkeypatch, evaluator, concurrency=4)
        )
        async with asyncio.timeout(1):
            while executor.submission_count < 5:
                await asyncio.sleep(0.005)
        run_task.cancel()
        await asyncio.sleep(0)
    finally:
        blocker_release.set()
        await blocker

    assert run_task is not None
    with pytest.raises(asyncio.CancelledError):
        await run_task


async def _cancel_run_while_sync_close_is_queued(
    monkeypatch: pytest.MonkeyPatch,
    evaluator: QueuedCloseSyncEvaluator,
) -> None:
    loop = asyncio.get_running_loop()
    executor = SubmissionTrackingExecutor(max_workers=1)
    loop.set_default_executor(executor)
    blocker_release = threading.Event()
    blocker_started = threading.Event()

    def occupy_only_worker() -> None:
        blocker_started.set()
        blocker_release.wait(timeout=5)

    blocker = loop.run_in_executor(None, occupy_only_worker)
    run_task: asyncio.Task[Any] | None = None
    try:
        async with asyncio.timeout(1):
            while not blocker_started.is_set():
                await asyncio.sleep(0.005)
        run_task = asyncio.create_task(_run_with_evaluator(monkeypatch, evaluator))
        async with asyncio.timeout(1):
            while not evaluator.evaluate_started.is_set():
                await asyncio.sleep(0.005)
        run_task.cancel()
        async with asyncio.timeout(1):
            while executor.submission_count < 2:
                await asyncio.sleep(0.005)
        run_task.cancel()
        await asyncio.sleep(0.02)
        assert not run_task.done()
    finally:
        blocker_release.set()
        await blocker

    assert run_task is not None
    with pytest.raises(asyncio.CancelledError):
        await run_task


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


class BlockingAsyncEvaluator:
    def __init__(self, *, expected_started: int) -> None:
        self.expected_started = expected_started
        self.release = asyncio.Event()
        self.all_started = asyncio.Event()
        self.active = 0
        self.peak_active = 0

    async def evaluate(self, sample: Any, target: Any) -> bool:
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        if self.active == self.expected_started:
            self.all_started.set()
        try:
            await self.release.wait()
            return _observation(sample)
        finally:
            self.active -= 1

    async def close(self) -> None:
        return None


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


class BlockingBatchEvaluator:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.first_batch_started = asyncio.Event()
        self.targets: list[str] = []

    async def evaluate_many(self, samples: list[Any], target: Any) -> list[bool]:
        self.targets.append(target.id)
        if len(self.targets) == 1:
            self.first_batch_started.set()
            await self.release.wait()
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


class QueuedCancellationSyncEvaluator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = 0
        self.closed = False

    def evaluate(self, sample: Any, target: Any) -> bool:
        with self._lock:
            self.started += 1
        return _observation(sample)

    def close(self) -> None:
        self.closed = True


class QueuedCloseSyncEvaluator:
    def __init__(self) -> None:
        self.evaluate_started = threading.Event()
        self.closed = False

    async def evaluate(self, sample: Any, target: Any) -> bool:
        self.evaluate_started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.closed = True


class CancellationFailureSyncEvaluator(CancellationTrackingSyncEvaluator):
    def evaluate(self, sample: Any, target: Any) -> bool:
        self._wait_for_release()
        raise RuntimeError(f"provider failure {sample.sample_index}")


class SubmissionTrackingExecutor(ThreadPoolExecutor):
    def __init__(self, *, max_workers: int) -> None:
        super().__init__(max_workers=max_workers)
        self._submission_lock = threading.Lock()
        self.submission_count = 0

    def submit(
        self,
        fn: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        with self._submission_lock:
            self.submission_count += 1
        return super().submit(fn, *args, **kwargs)
