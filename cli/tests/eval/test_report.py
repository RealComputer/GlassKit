from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from glasskit.eval.models import (
    EvalCase,
    EvalRunReport,
    EvalSuite,
    SampleExpectation,
    SampleResult,
    TargetSpec,
)
from glasskit.eval.report import (
    ConsoleReporter,
    print_run_summary,
    print_sample_schedule,
)


def test_print_run_summary_includes_formatted_duration() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    report = EvalRunReport(
        eval_dir=Path("eval"),
        case_names=[],
        results=[],
        gate_results=[],
        duration_s=125.5,
    )

    print_run_summary(report, console=console)

    assert "Duration: 2m 5.5s" in buffer.getvalue()


def test_print_run_summary_uses_target_label_with_id() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    report = EvalRunReport(
        eval_dir=Path("eval"),
        case_names=["case-001"],
        results=[_result()],
        gate_results=[],
        duration_s=1.0,
    )

    print_run_summary(report, console=console)

    assert "Step 1 (step_1)" in buffer.getvalue()


def test_print_sample_schedule_uses_target_label_with_id() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)

    print_sample_schedule(_suite(), console=console)

    assert "Step 1 (step_1)" in buffer.getvalue()


def test_console_reporter_uses_target_label_with_id() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    reporter = ConsoleReporter(verbose=True, console=console)

    reporter.on_target_start(_case(), "step_1", 1)
    reporter.on_result(_result())

    output = buffer.getvalue()
    assert "target Step 1 (step_1): 1 samples" in output
    assert "Step 1 (step_1) @0s" in output


def _suite() -> EvalSuite:
    return EvalSuite(path=Path("eval"), cases=[_case()])


def _case() -> EvalCase:
    sample = SampleExpectation(
        case_name="case-001",
        target_id="step_1",
        target_index=0,
        target_label="Step 1",
        target_config={},
        video_path=Path("video.mp4"),
        timestamp_s=0.0,
        sample_index=0,
        expected=True,
    )
    target = TargetSpec(
        id="step_1",
        index=0,
        label="Step 1",
        config={},
        samples=[sample],
    )
    return EvalCase(
        name="case-001",
        path=Path("case-001.yaml"),
        video_path=Path("video.mp4"),
        description=None,
        targets=[target],
    )


def _result() -> SampleResult:
    return SampleResult(
        case_name="case-001",
        target_id="step_1",
        target_label="Step 1",
        sample_index=0,
        timestamp_s=0.0,
        status="failed",
        expected=True,
        observed=False,
        observed_value=False,
        compare_mode="exact",
        field=None,
        reason="mismatch",
        source="at",
    )
