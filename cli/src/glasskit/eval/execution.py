from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Generator, Mapping, Set
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from .adapters import LoadedEvaluator, load_evaluator
from .json_values import json_value_error
from .models import (
    AdapterConfig,
    AdapterRuntimeError,
    EvaluationTimingMode,
    FrameSample,
    SampleExpectation,
    TargetContext,
)
from .process_adapters import load_process_evaluator


class FrameCursor:
    def __init__(self, frames: Generator[FrameSample, None, None]) -> None:
        self._frames = frames
        self._cached: dict[int, FrameSample] = {}

    def take(self, sample: SampleExpectation) -> FrameSample:
        try:
            return self._cached.pop(sample.sample_index)
        except KeyError:
            pass

        for frame in self._frames:
            if frame.sample_index == sample.sample_index:
                return frame
            self._cached[frame.sample_index] = frame
        raise RuntimeError(
            "internal error: video decoder did not produce "
            f"sample {sample.sample_index} for {sample.case_name}/{sample.target_id}"
        )

    def close(self) -> None:
        for frame in self._cached.values():
            frame.image.close()
        self._cached.clear()
        self._frames.close()


@dataclass(frozen=True)
class EvaluationOutcome:
    sample: SampleExpectation
    observation: Any
    runtime_error: Exception | None
    duration_s: float
    timing_mode: EvaluationTimingMode


async def load_configured_evaluator(
    adapter: str | None,
    adapter_command: str | None,
    config: AdapterConfig,
) -> LoadedEvaluator:
    if adapter_command is not None:
        return await load_process_evaluator(adapter_command, config)
    if adapter is not None:
        return await load_evaluator(adapter, config)
    raise RuntimeError("internal error: evaluator requested without an adapter")


async def close_evaluator(evaluator: LoadedEvaluator) -> None:
    active_error = sys.exc_info()[1]
    try:
        await evaluator.close()
    except Exception as close_error:
        if active_error is not None:
            active_error.add_note(
                f"adapter close failed while handling previous error: {close_error}"
            )
            return
        raise AdapterRuntimeError(
            f"adapter close failed: {close_error}"
        ) from close_error


async def evaluate_samples[ResultT](
    evaluator: LoadedEvaluator,
    frame_cursor: FrameCursor,
    samples: list[SampleExpectation],
    target: TargetContext,
    *,
    concurrency: int,
    keep_going: bool,
    transform: Callable[[EvaluationOutcome, FrameSample], ResultT],
) -> list[ResultT]:
    if not samples:
        return []
    if evaluator.supports_batch_evaluation:
        frames = [frame_cursor.take(sample) for sample in samples]
        try:
            evaluations = await _evaluate_sample_batch(
                evaluator,
                frames,
                samples,
                target,
                keep_going=keep_going,
            )
            return [
                transform(evaluation, frame)
                for evaluation, frame in zip(evaluations, frames, strict=True)
            ]
        finally:
            _close_frames(frames)
    return await _evaluate_samples_individually(
        evaluator,
        frame_cursor,
        samples,
        target,
        concurrency=concurrency,
        keep_going=keep_going,
        transform=transform,
    )


async def _evaluate_sample_batch(
    evaluator: LoadedEvaluator,
    frames: list[FrameSample],
    samples: list[SampleExpectation],
    target: TargetContext,
    *,
    keep_going: bool,
) -> list[EvaluationOutcome]:
    started_at = perf_counter()
    try:
        observations = await evaluator.evaluate_many(frames, target)
        if isinstance(observations, (str, bytes, bytearray, Mapping, Set)):
            raise AdapterRuntimeError(
                f"adapter returned {type(observations).__name__} instead of a "
                f"sequence of observations for target {target.id!r}"
            )
        observation_items = list(observations)
        if len(observation_items) != len(samples):
            raise AdapterRuntimeError(
                f"adapter returned {len(observation_items)} observations for "
                f"{len(samples)} samples in target {target.id!r}"
            )
    except Exception as error:
        duration_s = _elapsed_seconds(started_at)
        runtime_error = _batch_adapter_runtime_error(error, target)
        if not keep_going:
            if runtime_error is error:
                raise runtime_error from None
            raise runtime_error from error
        amortized_duration_s = duration_s / len(samples)
        return [
            EvaluationOutcome(
                sample=sample,
                observation=None,
                runtime_error=runtime_error,
                duration_s=amortized_duration_s,
                timing_mode="batch_amortized",
            )
            for sample in samples
        ]

    amortized_duration_s = _elapsed_seconds(started_at) / len(samples)
    return [
        _validated_observation(
            sample,
            observation,
            duration_s=amortized_duration_s,
            timing_mode="batch_amortized",
            keep_going=keep_going,
        )
        for sample, observation in zip(samples, observation_items, strict=True)
    ]


async def _evaluate_samples_individually[ResultT](
    evaluator: LoadedEvaluator,
    frame_cursor: FrameCursor,
    samples: list[SampleExpectation],
    target: TargetContext,
    *,
    concurrency: int,
    keep_going: bool,
    transform: Callable[[EvaluationOutcome, FrameSample], ResultT],
) -> list[ResultT]:
    async def evaluate_index(index: int) -> ResultT:
        sample = samples[index]
        frame = frame_cursor.take(sample)
        try:
            started_at = perf_counter()
            try:
                observation = await evaluator.evaluate(frame, target)
            except Exception as error:
                duration_s = _elapsed_seconds(started_at)
                runtime_error = _sample_adapter_runtime_error(error, sample)
                if not keep_going:
                    if runtime_error is error:
                        raise runtime_error from None
                    raise runtime_error from error
                evaluation = EvaluationOutcome(
                    sample=sample,
                    observation=None,
                    runtime_error=runtime_error,
                    duration_s=duration_s,
                    timing_mode="individual",
                )
            else:
                evaluation = _validated_observation(
                    sample,
                    observation,
                    duration_s=_elapsed_seconds(started_at),
                    timing_mode="individual",
                    keep_going=keep_going,
                )
            return transform(evaluation, frame)
        finally:
            frame.image.close()

    return await _bounded_map(
        len(samples),
        concurrency=concurrency,
        evaluate_index=evaluate_index,
    )


async def _bounded_map[ResultT](
    item_count: int,
    *,
    concurrency: int,
    evaluate_index: Callable[[int], Awaitable[ResultT]],
) -> list[ResultT]:
    results: list[ResultT | None] = [None] * item_count
    next_index = 0
    stopped = False
    errors: list[tuple[int, Exception]] = []

    async def worker() -> None:
        nonlocal next_index, stopped
        while not stopped:
            index = next_index
            if index >= item_count:
                return
            next_index += 1
            try:
                results[index] = await evaluate_index(index)
            except Exception as error:
                errors.append((index, error))
                stopped = True

    workers = [
        asyncio.create_task(worker()) for _ in range(min(concurrency, item_count))
    ]
    try:
        await asyncio.gather(*workers)
    except asyncio.CancelledError as cancellation:
        for worker_task in workers:
            worker_task.cancel()
        for note in await _drain_workers(workers):
            cancellation.add_note(note)
        raise
    if errors:
        _, error = min(errors, key=lambda item: item[0])
        raise error
    if any(result is None for result in results):
        raise RuntimeError("internal error: concurrent evaluation left missing results")
    return [result for result in results if result is not None]


async def _drain_workers(workers: list[asyncio.Task[None]]) -> list[str]:
    pending = asyncio.gather(*workers, return_exceptions=True)
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            continue
    pending.result()
    notes: list[str] = []
    for worker in workers:
        try:
            worker.result()
        except asyncio.CancelledError as cancellation:
            notes.extend(getattr(cancellation, "__notes__", ()))
        except BaseException as error:
            notes.append(
                f"evaluation worker failed while draining cancellation: {error}"
            )
    return notes


def _validated_observation(
    sample: SampleExpectation,
    observation: Any,
    *,
    duration_s: float,
    timing_mode: EvaluationTimingMode,
    keep_going: bool,
) -> EvaluationOutcome:
    if error_message := json_value_error(observation, label="observation"):
        error = AdapterRuntimeError(
            "adapter returned non-JSON observation for "
            f"{sample.case_name}/{sample.target_id} sample "
            f"{sample.sample_index}: {error_message}"
        )
        if not keep_going:
            raise error
        return EvaluationOutcome(
            sample=sample,
            observation=None,
            runtime_error=error,
            duration_s=duration_s,
            timing_mode=timing_mode,
        )
    return EvaluationOutcome(
        sample=sample,
        observation=observation,
        runtime_error=None,
        duration_s=duration_s,
        timing_mode=timing_mode,
    )


def _elapsed_seconds(started_at: float) -> float:
    return max(0.0, perf_counter() - started_at)


def _batch_adapter_runtime_error(error: Exception, target: TargetContext) -> Exception:
    if isinstance(error, AdapterRuntimeError):
        return error
    return AdapterRuntimeError(f"adapter failed for target {target.id!r}: {error}")


def _sample_adapter_runtime_error(
    error: Exception, sample: SampleExpectation
) -> Exception:
    if isinstance(error, AdapterRuntimeError):
        return error
    return AdapterRuntimeError(
        "adapter failed for "
        f"{sample.case_name}/{sample.target_id} sample {sample.sample_index} "
        f"at {sample.timestamp_s:g}s: {error}"
    )


def _close_frames(frames: list[FrameSample]) -> None:
    for frame in frames:
        frame.image.close()
