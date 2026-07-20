from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from PIL import Image

from glasskit.eval import process_adapters
from glasskit.eval.commands import serialize_command
from glasskit.eval.models import (
    AdapterConfig,
    AdapterLoadError,
    AdapterRuntimeError,
    EvalConfigError,
    FrameSample,
    RunOptions,
    TargetContext,
)
from glasskit.eval.process_adapters import load_process_evaluator
from glasskit.eval.runner import run_eval, validate_eval_directory

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PROCESS_ADAPTER = FIXTURES / "adapters" / "process_adapter.py"
TWO_STATE_EVAL = FIXTURES / "eval_directories" / "two-state"


def test_process_adapter_transports_individual_sample_config_and_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    asyncio.run(_run_individual_process_adapter_test(tmp_path))

    captured = capsys.readouterr()
    assert "fixture adapter log" in captured.err


async def _run_individual_process_adapter_test(tmp_path: Path) -> None:
    lifecycle_path = tmp_path / "lifecycle.txt"
    artifacts_dir = tmp_path / "artifacts"
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=tmp_path,
            artifacts_dir=artifacts_dir,
            verbose=True,
            config={
                "lifecyclePath": str(lifecycle_path),
                "stderrMessage": "fixture adapter log",
            },
        ),
    )
    sample = _sample(2)
    try:
        result = await evaluator.evaluate(
            sample,
            TargetContext(
                id="step_2",
                index=1,
                label="Second step",
                config={"prompt": "check it"},
            ),
        )
    finally:
        sample.image.close()
        await evaluator.close()

    assert evaluator.supports_individual_evaluation
    assert not evaluator.supports_batch_evaluation
    assert result["target"] == "step_2"
    assert result["targetIndex"] == 1
    assert result["targetLabel"] == "Second step"
    assert result["targetConfig"] == {"prompt": "check it"}
    assert result["timestampS"] == 1.0
    assert result["frameIndex"] == 12
    assert result["sampleIndex"] == 2
    assert result["videoPath"] == "recordings/case.mp4"
    assert result["caseName"] == "case"
    assert result["image"]["mimeType"] == "image/png"
    assert result["image"]["width"] == 4
    assert result["image"]["height"] == 3
    assert result["image"]["byteLength"] > 0
    assert result["initializeConfig"] == {
        "evalDir": str(tmp_path.resolve()),
        "config": {
            "lifecyclePath": str(lifecycle_path),
            "stderrMessage": "fixture adapter log",
        },
        "artifactsDir": str(artifacts_dir.resolve()),
        "verbose": True,
    }
    assert lifecycle_path.read_text(encoding="utf-8").splitlines() == [
        "initialize",
        "close",
    ]


def test_process_adapter_uses_advertised_batch_strategy() -> None:
    asyncio.run(_run_batch_process_adapter_test())


async def _run_batch_process_adapter_test() -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(eval_dir=TWO_STATE_EVAL, config={"strategy": "both"}),
    )
    samples = [_sample(0), _sample(1)]
    try:
        result = await evaluator.evaluate_many(
            samples, TargetContext(id="step", index=0)
        )
    finally:
        for sample in samples:
            sample.image.close()
        await evaluator.close()

    assert evaluator.supports_individual_evaluation
    assert evaluator.supports_batch_evaluation
    assert [item["sampleIndex"] for item in result] == [0, 1]


def test_process_adapter_multiplexes_concurrent_requests() -> None:
    asyncio.run(_run_concurrent_process_adapter_test())


async def _run_concurrent_process_adapter_test() -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={"delayS": 0.1, "reverseDelay": True},
        ),
    )
    samples = [_sample(index) for index in range(3)]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *[
                    evaluator.evaluate(sample, TargetContext(id="step", index=0))
                    for sample in samples
                ]
            ),
            timeout=0.65,
        )
    finally:
        for sample in samples:
            sample.image.close()
        await evaluator.close()

    assert [result["sampleIndex"] for result in results] == [0, 1, 2]


def test_process_adapter_surfaces_structured_evaluation_errors() -> None:
    asyncio.run(_run_process_adapter_error_test())


async def _run_process_adapter_error_test() -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={"failMessage": "model backend unavailable"},
        ),
    )
    sample = _sample(0)
    try:
        with pytest.raises(
            AdapterRuntimeError,
            match="adapter command evaluate failed: model backend unavailable",
        ):
            await evaluator.evaluate(sample, TargetContext(id="step", index=0))
    finally:
        sample.image.close()
        await evaluator.close()


def test_process_adapter_rejects_stdout_logs_with_actionable_error() -> None:
    asyncio.run(_run_invalid_stdout_test())


async def _run_invalid_stdout_test() -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={"invalidStdout": True},
        ),
    )
    sample = _sample(0)
    try:
        with pytest.raises(AdapterRuntimeError) as exc_info:
            await evaluator.evaluate(sample, TargetContext(id="step", index=0))
        assert "invalid JSON on stdout" in str(exc_info.value)
        assert "write adapter logs to stderr" in str(exc_info.value)
    finally:
        sample.image.close()
        with pytest.raises(AdapterRuntimeError):
            await evaluator.close()


def test_process_adapter_reports_process_exit_and_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    asyncio.run(_run_process_exit_test())

    assert "fixture process exited during evaluate" in capsys.readouterr().err


async def _run_process_exit_test() -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={"exitDuringEvaluate": True},
        ),
    )
    sample = _sample(0)
    try:
        with pytest.raises(AdapterRuntimeError) as exc_info:
            await evaluator.evaluate(sample, TargetContext(id="step", index=0))
        assert "exit code 7" in str(exc_info.value)
        assert "fixture process exited during evaluate" in str(exc_info.value)
    finally:
        sample.image.close()
        with pytest.raises(AdapterRuntimeError):
            await evaluator.close()


def test_process_adapter_cancels_in_flight_request_before_close() -> None:
    asyncio.run(_run_process_cancellation_test())


async def _run_process_cancellation_test() -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(eval_dir=TWO_STATE_EVAL, config={"delayS": 2}),
    )
    sample = _sample(0)
    evaluation = asyncio.create_task(
        evaluator.evaluate(sample, TargetContext(id="step", index=0))
    )
    await asyncio.sleep(0.1)
    evaluation.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await evaluation
        await asyncio.wait_for(evaluator.close(), timeout=1)
    finally:
        sample.image.close()


def test_process_adapter_aborts_blocked_write_when_request_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shorten_shutdown_timeouts(monkeypatch)
    asyncio.run(_run_blocked_write_cancellation_test(tmp_path))


async def _run_blocked_write_cancellation_test(tmp_path: Path) -> None:
    blocked_marker = tmp_path / "adapter-stopped-reading"
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={
                "blockStdinAfterEvaluateMarker": str(blocked_marker),
                "delayS": 30,
            },
        ),
    )
    samples = [_sample(0), _sample(1)]
    first_evaluation = asyncio.create_task(
        evaluator.evaluate(samples[0], TargetContext(id="step", index=0))
    )
    await _wait_for_path(blocked_marker)
    blocked_evaluation = asyncio.create_task(
        evaluator.evaluate(
            samples[1],
            TargetContext(
                id="step",
                index=0,
                config={"largePayload": "x" * (2 * 1024 * 1024)},
            ),
        )
    )
    await asyncio.sleep(0.1)
    assert not blocked_evaluation.done()
    blocked_evaluation.cancel()
    done, _ = await asyncio.wait({blocked_evaluation}, timeout=1)

    try:
        if blocked_evaluation not in done:
            with pytest.raises(AdapterRuntimeError):
                await evaluator.close()
            await asyncio.gather(blocked_evaluation, return_exceptions=True)
            pytest.fail("evaluation cancellation stayed blocked in the stdin write")
        with pytest.raises(asyncio.CancelledError):
            await blocked_evaluation
        first_result = await asyncio.wait_for(
            asyncio.gather(first_evaluation, return_exceptions=True),
            timeout=1,
        )
        assert isinstance(first_result[0], AdapterRuntimeError)
        await asyncio.wait_for(evaluator.close(), timeout=1)
    finally:
        for sample in samples:
            sample.image.close()
        for evaluation in (first_evaluation, blocked_evaluation):
            if not evaluation.done():
                evaluation.cancel()
        await asyncio.gather(
            first_evaluation, blocked_evaluation, return_exceptions=True
        )


def test_process_adapter_shields_blocked_write_cleanup_from_repeated_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shorten_shutdown_timeouts(monkeypatch)
    asyncio.run(_run_repeated_blocked_write_cancellation_test(tmp_path, monkeypatch))


async def _run_repeated_blocked_write_cancellation_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_marker = tmp_path / "adapter-stopped-reading"
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={
                "blockStdinAfterEvaluateMarker": str(blocked_marker),
                "delayS": 30,
            },
        ),
    )
    original_write_message = process_adapters._ProcessAdapter._write_message
    write_cancellation_started = asyncio.Event()
    release_write_cancellation = asyncio.Event()

    async def delay_write_cancellation(
        adapter: process_adapters._ProcessAdapter,
        message: bytes,
    ) -> None:
        try:
            await original_write_message(adapter, message)
        except asyncio.CancelledError:
            write_cancellation_started.set()
            await release_write_cancellation.wait()
            raise

    monkeypatch.setattr(
        process_adapters._ProcessAdapter,
        "_write_message",
        delay_write_cancellation,
    )
    samples = [_sample(0), _sample(1)]
    first_evaluation = asyncio.create_task(
        evaluator.evaluate(samples[0], TargetContext(id="step", index=0))
    )
    await _wait_for_path(blocked_marker)
    blocked_evaluation = asyncio.create_task(
        evaluator.evaluate(
            samples[1],
            TargetContext(
                id="step",
                index=0,
                config={"largePayload": "x" * (2 * 1024 * 1024)},
            ),
        )
    )
    await asyncio.sleep(0.1)
    assert not blocked_evaluation.done()
    blocked_evaluation.cancel()
    await asyncio.wait_for(write_cancellation_started.wait(), timeout=1)
    blocked_evaluation.cancel()
    release_write_cancellation.set()

    try:
        done, _ = await asyncio.wait({blocked_evaluation}, timeout=1)
        assert blocked_evaluation in done
        with pytest.raises(asyncio.CancelledError):
            await blocked_evaluation
        await asyncio.wait_for(evaluator.close(), timeout=1)
        first_result = await asyncio.wait_for(
            asyncio.gather(first_evaluation, return_exceptions=True),
            timeout=1,
        )
        assert isinstance(first_result[0], AdapterRuntimeError)
    finally:
        release_write_cancellation.set()
        try:
            await asyncio.wait_for(evaluator.close(), timeout=1)
        except BaseException:
            pass
        for sample in samples:
            sample.image.close()
        for evaluation in (first_evaluation, blocked_evaluation):
            if not evaluation.done():
                evaluation.cancel()
        await asyncio.gather(
            first_evaluation, blocked_evaluation, return_exceptions=True
        )


@pytest.mark.parametrize("mode", ["hangOnClose", "inheritPipesAfterClose"])
def test_process_adapter_bounds_entire_shutdown_sequence(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shorten_shutdown_timeouts(monkeypatch)
    asyncio.run(_run_bounded_shutdown_test(mode))


async def _run_bounded_shutdown_test(mode: str) -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(eval_dir=TWO_STATE_EVAL, config={mode: True}),
    )

    with pytest.raises(AdapterRuntimeError, match="did not complete close within"):
        await asyncio.wait_for(evaluator.close(), timeout=1)


def test_process_adapter_detects_leader_exit_while_child_holds_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shorten_shutdown_timeouts(monkeypatch)
    asyncio.run(_run_inherited_pipe_exit_test())


async def _run_inherited_pipe_exit_test() -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={"exitWithInheritedPipes": True},
        ),
    )
    sample = _sample(0)
    try:
        with pytest.raises(AdapterRuntimeError) as exc_info:
            await asyncio.wait_for(
                evaluator.evaluate(sample, TargetContext(id="step", index=0)),
                timeout=1,
            )
        assert "exit code 9" in str(exc_info.value)
        assert "fixture leader exited with inherited pipes" in str(exc_info.value)
    finally:
        sample.image.close()
        with pytest.raises(AdapterRuntimeError):
            await asyncio.wait_for(evaluator.close(), timeout=1)


def test_process_adapter_detects_leader_exit_during_initialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shorten_shutdown_timeouts(monkeypatch)

    with pytest.raises(AdapterLoadError) as exc_info:
        asyncio.run(
            asyncio.wait_for(
                load_process_evaluator(
                    _adapter_command(),
                    AdapterConfig(
                        eval_dir=TWO_STATE_EVAL,
                        config={"exitWithInheritedPipesOnInitialize": True},
                    ),
                ),
                timeout=1,
            )
        )
    assert "exit code 8" in str(exc_info.value)
    assert "fixture leader exited during initialize" in str(exc_info.value)


def test_process_adapter_unblocks_request_write_when_leader_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shorten_shutdown_timeouts(monkeypatch)
    asyncio.run(_run_exit_during_request_write_test(tmp_path))


async def _run_exit_during_request_write_test(tmp_path: Path) -> None:
    exit_marker = tmp_path / "exit-adapter"
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={"exitWhileRequestWritesMarker": str(exit_marker)},
        ),
    )
    sample = _sample(0)
    evaluation = asyncio.create_task(
        evaluator.evaluate(
            sample,
            TargetContext(
                id="step",
                index=0,
                config={"largePayload": "x" * (2 * 1024 * 1024)},
            ),
        )
    )
    await asyncio.sleep(0.1)
    exit_marker.touch()
    done, _ = await asyncio.wait({evaluation}, timeout=1)

    try:
        if evaluation not in done:
            with pytest.raises(AdapterRuntimeError):
                await evaluator.close()
            await asyncio.gather(evaluation, return_exceptions=True)
            pytest.fail(
                "evaluation stayed blocked in the stdin write after leader exit"
            )
        with pytest.raises(AdapterRuntimeError) as exc_info:
            await evaluation
        assert "exit code 10" in str(exc_info.value)
        assert "fixture leader exited while request was writing" in str(exc_info.value)
    finally:
        sample.image.close()
        if evaluation in done:
            with pytest.raises(AdapterRuntimeError):
                await evaluator.close()


def test_process_adapter_rejects_protocol_corruption_after_close_ack() -> None:
    asyncio.run(_run_late_protocol_corruption_test())


async def _run_late_protocol_corruption_test() -> None:
    evaluator = await load_process_evaluator(
        _adapter_command(),
        AdapterConfig(
            eval_dir=TWO_STATE_EVAL,
            config={"invalidStdoutAfterClose": True},
        ),
    )

    with pytest.raises(AdapterRuntimeError) as exc_info:
        await evaluator.close()
    assert "invalid JSON on stdout" in str(exc_info.value)
    assert "late stdout corruption" in str(exc_info.value)


def test_process_adapter_rejects_incompatible_protocol_version() -> None:
    with pytest.raises(
        AdapterLoadError, match="initialize result must declare protocolVersion 1"
    ):
        asyncio.run(
            load_process_evaluator(
                _adapter_command(),
                AdapterConfig(
                    eval_dir=TWO_STATE_EVAL,
                    config={"invalidProtocolVersion": True},
                ),
            )
        )


def test_process_adapter_reports_command_start_failure() -> None:
    with pytest.raises(AdapterLoadError, match="could not start adapter command"):
        asyncio.run(
            load_process_evaluator(
                "glasskit-command-that-does-not-exist",
                AdapterConfig(eval_dir=TWO_STATE_EVAL),
            )
        )


def test_runner_executes_process_adapter_and_recreates_it_for_each_trial(
    tmp_path: Path,
) -> None:
    lifecycle_path = tmp_path / "runner-lifecycle.txt"

    report = asyncio.run(
        run_eval(
            RunOptions(
                eval_dir=TWO_STATE_EVAL,
                adapter_command=_adapter_command(),
                adapter_config={
                    "booleanByTimestamp": True,
                    "lifecyclePath": str(lifecycle_path),
                },
                concurrency=2,
                repeat=2,
            )
        )
    )

    assert report.success
    assert report.repeat_count == 2
    assert lifecycle_path.read_text(encoding="utf-8").splitlines() == [
        "initialize",
        "close",
        "initialize",
        "close",
    ]


def test_runner_executes_process_adapter_batch_strategy() -> None:
    report = asyncio.run(
        run_eval(
            RunOptions(
                eval_dir=TWO_STATE_EVAL,
                adapter_command=_adapter_command(),
                adapter_config={
                    "booleanByTimestamp": True,
                    "strategy": "batch",
                },
                concurrency=4,
            )
        )
    )

    assert report.success
    assert report.evaluation_timing_mode == "batch_amortized"


def test_validate_constructs_and_closes_process_adapter(tmp_path: Path) -> None:
    lifecycle_path = tmp_path / "validate-lifecycle.txt"

    report = asyncio.run(
        validate_eval_directory(
            RunOptions(
                eval_dir=TWO_STATE_EVAL,
                adapter_command=_adapter_command(),
                adapter_config={"lifecyclePath": str(lifecycle_path)},
            )
        )
    )

    assert report.ok
    assert lifecycle_path.read_text(encoding="utf-8").splitlines() == [
        "initialize",
        "close",
    ]


def test_validate_bounds_hung_process_adapter_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shorten_shutdown_timeouts(monkeypatch)

    report = asyncio.run(
        asyncio.wait_for(
            validate_eval_directory(
                RunOptions(
                    eval_dir=TWO_STATE_EVAL,
                    adapter_command=_adapter_command(),
                    adapter_config={"hangOnClose": True},
                )
            ),
            timeout=1,
        )
    )

    assert not report.ok
    assert "did not complete close within" in report.issues[-1].message


@pytest.mark.parametrize("validate", [False, True])
def test_runner_rejects_python_and_process_adapter_together(validate: bool) -> None:
    options = RunOptions(
        eval_dir=TWO_STATE_EVAL,
        adapter="adapter.py:create_evaluator",
        adapter_command=_adapter_command(),
    )

    if validate:
        report = asyncio.run(validate_eval_directory(options))
        assert not report.ok
        assert report.issues[-1].message == (
            "adapter and adapter command are mutually exclusive"
        )
    else:
        with pytest.raises(
            EvalConfigError,
            match="adapter and adapter command are mutually exclusive",
        ):
            asyncio.run(run_eval(options))


def _adapter_command() -> str:
    return serialize_command([sys.executable, str(PROCESS_ADAPTER)])


def _shorten_shutdown_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_adapters, "GRACEFUL_EXIT_TIMEOUT_S", 0.15)
    monkeypatch.setattr(process_adapters, "TERMINATE_TIMEOUT_S", 0.15)
    monkeypatch.setattr(process_adapters, "EXIT_STATUS_TIMEOUT_S", 0.05)


async def _wait_for_path(path: Path) -> None:
    async with asyncio.timeout(1):
        while not path.exists():
            await asyncio.sleep(0.01)


def _sample(index: int) -> FrameSample:
    return FrameSample(
        image=Image.new("RGB", (4, 3), (index * 30, 20, 10)),
        timestamp_s=index * 0.5,
        frame_index=index + 10,
        sample_index=index,
        video_path="recordings/case.mp4",
        case_name="case",
    )
