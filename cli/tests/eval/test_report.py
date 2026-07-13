from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

from rich.console import Console

from glasskit.eval.models import (
    EvalCase,
    EvalDirectory,
    EvalRunReport,
    EvaluationTimingMode,
    ResultStatus,
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


def test_print_run_summary_includes_individual_timing_and_throughput() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)

    print_run_summary(_report(), console=console)

    output = buffer.getvalue()
    assert "Avg evaluation latency: 1.25s/sample" in output
    assert "Throughput: 1.00 samples/s" in output
    assert "Avg latency" in output
    assert "1.25s" in output


def test_print_run_summary_labels_amortized_batch_timing() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)

    print_run_summary(
        _report(
            evaluation_duration_s=0.5,
            evaluation_timing_mode="batch_amortized",
        ),
        console=console,
    )

    output = buffer.getvalue()
    assert "Avg amortized batch time: 500ms/sample" in output
    assert "Avg batch/sample" in output


def test_print_sample_schedule_uses_target_label_with_id() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)

    print_sample_schedule(_eval_directory(), console=console)

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


def test_console_reporter_does_not_auto_highlight_values() -> None:
    buffer = StringIO()
    console = Console(
        file=buffer,
        force_terminal=True,
        color_system="standard",
        no_color=False,
        width=120,
    )
    reporter = ConsoleReporter(verbose=True, console=console)

    reporter.on_case_start(_case(), 513)
    reporter.on_target_start(_case(), "step_1", 102)
    reporter.on_result(_result())

    assert buffer.getvalue() == (
        "\x1b[1mCase\x1b[0m case-001 (513 samples, video=video.mp4)\n"
        "  target Step 1 (step_1): 102 samples\n"
        "    \x1b[31mFAILED\x1b[0m Step 1 (step_1) @0s "
        "expected=True observed=False reason=mismatch\n"
    )


def test_ignore_reasons_render_as_literal_rich_text() -> None:
    reason = "tracking [/] [bold]flaky[/bold] C:\\"

    schedule_buffer = StringIO()
    print_sample_schedule(
        _eval_directory(ignore_reason=reason),
        console=Console(file=schedule_buffer, force_terminal=False, width=200),
    )

    result_buffer = StringIO()
    reporter = ConsoleReporter(
        verbose=False,
        console=Console(file=result_buffer, force_terminal=False, width=200),
    )
    reporter.on_result(_result(status="ignored", reason=reason))

    assert reason.endswith("\\")
    assert reason in schedule_buffer.getvalue()
    assert f"reason={reason}" in result_buffer.getvalue()


def test_run_summary_counts_ignored_samples_without_listing_them_as_failures() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    ignored = replace(
        _result(status="ignored", reason="Known flaky observation."),
        evaluation_duration_s=None,
        evaluation_timing_mode=None,
    )
    report = EvalRunReport(
        eval_dir=Path("eval"),
        case_names=["case-001"],
        results=[ignored],
        gate_results=[],
        duration_s=1.0,
    )

    print_run_summary(report, console=console)

    output = buffer.getvalue()
    assert "0 evaluated" in output
    assert "1 ignored" in output
    assert "Failures" not in output


def test_table_reports_render_markup_like_target_labels_literally() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)

    print_sample_schedule(
        _eval_directory(target_label="Segment [draft]"), console=console
    )
    print_run_summary(
        _report(target_label="Segment [draft]"),
        console=console,
    )

    output = buffer.getvalue()
    assert "Segment [draft] (step_1)" in output


def _eval_directory(
    *, target_label: str = "Step 1", ignore_reason: str | None = None
) -> EvalDirectory:
    return EvalDirectory(
        path=Path("eval"),
        cases=[_case(target_label=target_label, ignore_reason=ignore_reason)],
    )


def _case(
    *, target_label: str = "Step 1", ignore_reason: str | None = None
) -> EvalCase:
    sample = SampleExpectation(
        case_name="case-001",
        target_id="step_1",
        target_index=0,
        target_label=target_label,
        target_config={},
        video_path=Path("video.mp4"),
        timestamp_s=0.0,
        sample_index=0,
        expected=True,
        ignore=ignore_reason,
    )
    target = TargetSpec(
        id="step_1",
        index=0,
        label=target_label,
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


def _report(
    *,
    target_label: str = "Step 1",
    evaluation_duration_s: float = 1.25,
    evaluation_timing_mode: EvaluationTimingMode = "individual",
) -> EvalRunReport:
    return EvalRunReport(
        eval_dir=Path("eval"),
        case_names=["case-001"],
        results=[
            _result(
                target_label=target_label,
                evaluation_duration_s=evaluation_duration_s,
                evaluation_timing_mode=evaluation_timing_mode,
            )
        ],
        gate_results=[],
        duration_s=1.0,
    )


def _result(
    *,
    target_label: str = "Step 1",
    evaluation_duration_s: float = 1.25,
    evaluation_timing_mode: EvaluationTimingMode = "individual",
    status: ResultStatus = "failed",
    reason: str = "mismatch",
) -> SampleResult:
    return SampleResult(
        case_name="case-001",
        target_id="step_1",
        target_label=target_label,
        sample_index=0,
        timestamp_s=0.0,
        status=status,
        expected=True,
        observed=False,
        observed_value=False,
        compare_mode="exact",
        field=None,
        reason=reason,
        source="at",
        evaluation_duration_s=evaluation_duration_s,
        evaluation_timing_mode=evaluation_timing_mode,
    )
