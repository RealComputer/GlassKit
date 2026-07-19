from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path

import pytest
from PIL import Image

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
    return shlex.join([sys.executable, str(PROCESS_ADAPTER)])


def _sample(index: int) -> FrameSample:
    return FrameSample(
        image=Image.new("RGB", (4, 3), (index * 30, 20, 10)),
        timestamp_s=index * 0.5,
        frame_index=index + 10,
        sample_index=index,
        video_path="recordings/case.mp4",
        case_name="case",
    )
