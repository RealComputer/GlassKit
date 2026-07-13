from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

from rich.console import Console

from glasskit.eval.models import (
    EvalCase,
    EvalDirectory,
    EvalRunReport,
    EvalTrialReport,
    EvaluationTimingMode,
    GateResult,
    ResultStatus,
    SampleExpectation,
    SampleResult,
    SampleStability,
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
    report = _report(results=[], case_names=[], duration_s=125.5)

    print_run_summary(report, console=console)

    assert "Duration: 2m 5.5s" in buffer.getvalue()


def test_print_run_summary_uses_target_label_with_id() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    report = _report()

    print_run_summary(report, console=console)

    assert "Step 1 (step_1)" in buffer.getvalue()


def test_print_run_summary_includes_individual_timing_and_throughput() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)

    print_run_summary(_report(), console=console)

    output = buffer.getvalue()
    assert "Avg evaluation latency: 1.25s/attempt" in output
    assert "Throughput: 1.00 attempts/s" in output


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
    assert "Avg amortized batch time: 500ms/attempt" in output


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


def test_console_reporter_labels_repeated_trial_output() -> None:
    buffer = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=Console(file=buffer, force_terminal=False, width=120),
    )

    reporter.on_trial_start(2, 3)
    reporter.on_result(_result())

    output = buffer.getvalue()
    assert "Trial 2/3" in output
    assert "[2/3] FAILED" in output


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
    report = _report(results=[ignored])

    print_run_summary(report, console=console)

    output = buffer.getvalue()
    assert "0 evaluated per trial" in output
    assert "1 ignored" in output
    assert "Unstable and failing samples" not in output


def test_run_summary_lists_consistently_failed_samples() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    report = _report(
        repeat=2,
        trial_gates=[
            GateResult(
                name="adapter_errors",
                passed=True,
                message="no adapter/comparison errors",
            )
        ],
    )

    print_run_summary(report, console=console)

    output = buffer.getvalue()
    assert "Trial pass rate (min / mean / max): 0.0% / 0.0% / 0.0%" in output
    assert "Unstable and failing samples" in output
    assert "failed every trial" in output
    assert "Failed gates" not in output
    assert "adapter_errors" not in output


def test_run_summary_prints_only_failed_gates() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    report = _report(
        trial_gates=[
            GateResult(
                name="adapter_errors",
                passed=True,
                message="no adapter/comparison errors",
            ),
            GateResult(
                name="eval_min_pass_rate",
                passed=False,
                message="0.0% pass rate (gate: >= 95.0%)",
            ),
        ]
    )

    print_run_summary(report, console=console)

    output = buffer.getvalue()
    assert "Failed gates" in output
    assert "eval_min_pass_rate" in output
    assert "0.0% pass rate (gate: >= 95.0%)" in output
    assert "Trial 1" in output
    assert "adapter_errors" not in output


def test_run_summary_reports_cross_trial_stability() -> None:
    buffer = StringIO()
    passed = _result(status="passed", reason="matched")
    failed = _result()
    trial_gate = GateResult(
        name="eval_min_pass_rate",
        passed=False,
        message="0.0% pass rate (gate: >= 100.0%)",
    )
    stability_gate = GateResult(
        name="max_flaky_samples",
        passed=False,
        message="1 flaky sample (gate: <= 0)",
    )
    report = EvalRunReport(
        eval_dir=Path("eval"),
        case_names=["case-001"],
        trials=[
            EvalTrialReport(1, [passed], [], 1.0),
            EvalTrialReport(2, [failed], [trial_gate], 1.0),
            EvalTrialReport(3, [passed], [], 1.0),
        ],
        stability=[
            SampleStability(
                case_name="case-001",
                target_id="step_1",
                target_label="Step 1",
                sample_index=0,
                timestamp_s=0.0,
                expected=True,
                source="at",
                statuses=("passed", "failed", "passed"),
            )
        ],
        gate_results=[stability_gate],
        duration_s=3.0,
    )

    print_run_summary(
        report,
        console=Console(file=buffer, force_terminal=False, width=160),
    )

    output = buffer.getvalue()
    assert "Trials: 3 total, 2 passed gates, 1 failed gates" in output
    assert "Trial pass rate (min / mean / max): 0.0% / 66.7% / 100.0%" in output
    assert "1 flaky" in output
    assert "P/F/P" in output
    assert "max_flaky_samples" in output


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
    results: list[SampleResult] | None = None,
    trial_gates: list[GateResult] | None = None,
    stability_gates: list[GateResult] | None = None,
    case_names: list[str] | None = None,
    duration_s: float = 1.0,
    repeat: int = 1,
) -> EvalRunReport:
    if results is None:
        results = [
            _result(
                target_label=target_label,
                evaluation_duration_s=evaluation_duration_s,
                evaluation_timing_mode=evaluation_timing_mode,
            )
        ]
    return EvalRunReport(
        eval_dir=Path("eval"),
        case_names=["case-001"] if case_names is None else case_names,
        trials=[
            EvalTrialReport(
                index=index,
                results=results,
                gate_results=trial_gates or [],
                duration_s=duration_s,
            )
            for index in range(1, repeat + 1)
        ],
        stability=[_stability(result, repeat=repeat) for result in results],
        gate_results=stability_gates or [],
        duration_s=duration_s,
    )


def _stability(result: SampleResult, *, repeat: int) -> SampleStability:
    return SampleStability(
        case_name=result.case_name,
        target_id=result.target_id,
        target_label=result.target_label,
        sample_index=result.sample_index,
        timestamp_s=result.timestamp_s,
        expected=result.expected,
        source=result.source,
        statuses=(result.status,) * repeat,
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
