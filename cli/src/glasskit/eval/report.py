from __future__ import annotations

from collections import defaultdict
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from .expectations import format_sample_schedule
from .models import (
    EvalCase,
    EvalDirectory,
    EvalRunReport,
    SampleResult,
    ValidationReport,
)


class ConsoleReporter:
    def __init__(
        self, *, verbose: bool = False, console: Console | None = None
    ) -> None:
        self.verbose = verbose
        self.console = console or Console()

    def on_case_start(self, case: EvalCase, sample_count: int) -> None:
        self.console.print(
            f"[bold]Case[/bold] {case.name} "
            f"({sample_count} samples, video={case.video_path.name})",
            highlight=False,
        )

    def on_target_start(
        self, case: EvalCase, target_id: str, sample_count: int
    ) -> None:
        target_label = _target_label_for_case(case, target_id)
        target_name = escape(_format_target_name(target_id, target_label))
        self.console.print(
            f"  target {target_name}: {sample_count} samples",
            highlight=False,
        )

    def on_result(self, result: SampleResult) -> None:
        if result.status == "passed" and not self.verbose:
            return
        style = {
            "passed": "green",
            "ignored": "yellow",
        }.get(result.status, "red")
        line = Text("    ")
        line.append(result.status.upper(), style=style)
        line.append(
            f" {_format_target_name(result.target_id, result.target_label)} "
            f"@{result.timestamp_s:g}s "
            f"expected={_short(result.expected)} "
            f"observed={_short(result.observed_value)} "
            f"reason={result.reason}"
        )
        self.console.print(line, highlight=False)


def print_validation_report(
    report: ValidationReport, console: Console | None = None
) -> None:
    console = console or Console()
    if report.ok:
        eval_directory_name = (
            str(report.eval_directory.path)
            if report.eval_directory is not None
            else "<none>"
        )
        sample_count = (
            len(report.eval_directory.samples)
            if report.eval_directory is not None
            else 0
        )
        console.print(
            f"[green]Validation passed[/green]: {eval_directory_name} "
            f"({sample_count} samples)",
            highlight=False,
        )
        return
    console.print("[red]Validation failed[/red]", highlight=False)
    for issue in report.issues:
        location = f"{issue.path}: " if issue.path else ""
        console.print(f"- {location}{issue.message}", highlight=False)


def print_sample_schedule(
    eval_directory: EvalDirectory, console: Console | None = None
) -> None:
    console = console or Console()
    table = Table(title=f"Samples: {eval_directory.path}")
    for column in (
        "Case",
        "Target",
        "Time",
        "Expected",
        "Mode",
        "Field",
        "Ignored",
        "Source",
    ):
        table.add_column(column)
    for row in format_sample_schedule(eval_directory):
        table.add_row(
            str(row["case"]),
            _format_target_text(str(row["target"]), row.get("target_label")),
            f"{row['timestamp_s']:g}s",
            _short(row["expected"]),
            str(row["mode"] or ""),
            str(row["field"] or ""),
            Text(str(row["ignore"] or "")),
            str(row["source"] or ""),
        )
    console.print(table)


def print_run_summary(
    report: EvalRunReport,
    *,
    max_failures_to_print: int = 20,
    console: Console | None = None,
) -> None:
    console = console or Console()
    status = "[green]passed[/green]" if report.success else "[red]failed[/red]"
    console.print(f"\n[bold]Eval[/bold]: {report.eval_dir}", highlight=False)
    console.print(f"Cases: {len(report.case_names)}", highlight=False)
    console.print(
        "Samples: "
        f"{report.evaluated_count} evaluated, "
        f"{report.passed_count} passed, "
        f"{report.failed_count} failed, "
        f"{report.error_count} errors, "
        f"{report.ignored_count} ignored",
        highlight=False,
    )
    console.print(f"Pass rate: {report.pass_rate:.1%} ({status})", highlight=False)
    console.print(f"Duration: {_format_duration(report.duration_s)}", highlight=False)
    if report.average_evaluation_duration_s is not None:
        timing_label = _summary_timing_label(report.evaluation_timing_mode)
        console.print(
            f"{timing_label}: "
            f"{_format_evaluation_duration(report.average_evaluation_duration_s)}"
            "/sample",
            highlight=False,
        )
        console.print(
            f"Throughput: {report.throughput_samples_per_s:.2f} samples/s",
            highlight=False,
        )

    if report.gate_results:
        gate_table = Table(title="Gates")
        gate_table.add_column("Gate")
        gate_table.add_column("Status")
        gate_table.add_column("Detail")
        for gate in report.gate_results:
            gate_table.add_row(
                gate.name,
                "passed" if gate.passed else "failed",
                gate.message,
            )
        console.print(gate_table)

    target_table = Table(title="By target")
    target_table.add_column("Target")
    target_table.add_column("Pass rate", justify="right")
    target_table.add_column("Passed", justify="right")
    target_table.add_column("Evaluated", justify="right")
    target_table.add_column("Ignored", justify="right")
    show_timing = report.average_evaluation_duration_s is not None
    if show_timing:
        target_table.add_column(
            _target_timing_column(report.evaluation_timing_mode), justify="right"
        )
    for target_id, target_results in _group_by_target(report.results).items():
        passed = sum(1 for result in target_results if result.status == "passed")
        ignored = sum(1 for result in target_results if result.status == "ignored")
        total = len(target_results) - ignored
        pass_rate = passed / total if total else 0.0
        target_label = _first_target_label(target_results)
        row = [
            _format_target_text(target_id, target_label),
            f"{pass_rate:.1%}",
            str(passed),
            str(total),
            str(ignored),
        ]
        if show_timing:
            average_duration_s = _average_evaluation_duration(target_results)
            row.append(
                "n/a"
                if average_duration_s is None
                else _format_evaluation_duration(average_duration_s)
            )
        target_table.add_row(*row)
    console.print(target_table)

    failures = [
        result for result in report.results if result.status in {"failed", "error"}
    ]
    if failures:
        failure_table = Table(title=f"Failures (first {max_failures_to_print})")
        for column in (
            "Case",
            "Target",
            "Time",
            "Status",
            "Expected",
            "Observed",
            "Reason",
        ):
            failure_table.add_column(column)
        for result in failures[:max_failures_to_print]:
            failure_table.add_row(
                result.case_name,
                _format_target_text(result.target_id, result.target_label),
                f"{result.timestamp_s:g}s",
                result.status,
                _short(result.expected),
                _short(result.observed_value),
                result.reason,
            )
        console.print(failure_table)


def _group_by_target(results: list[SampleResult]) -> dict[str, list[SampleResult]]:
    grouped: dict[str, list[SampleResult]] = defaultdict(list)
    for result in results:
        grouped[result.target_id].append(result)
    return dict(sorted(grouped.items()))


def _first_target_label(results: list[SampleResult]) -> str | None:
    return next(
        (result.target_label for result in results if result.target_label), None
    )


def _average_evaluation_duration(results: list[SampleResult]) -> float | None:
    durations = [
        result.evaluation_duration_s
        for result in results
        if result.status != "ignored" and result.evaluation_duration_s is not None
    ]
    if not durations:
        return None
    return sum(durations) / len(durations)


def _summary_timing_label(mode: str | None) -> str:
    if mode == "individual":
        return "Avg evaluation latency"
    if mode == "batch_amortized":
        return "Avg amortized batch time"
    return "Avg evaluation time"


def _target_timing_column(mode: str | None) -> str:
    if mode == "individual":
        return "Avg latency"
    if mode == "batch_amortized":
        return "Avg batch/sample"
    return "Avg eval/sample"


def _target_label_for_case(case: EvalCase, target_id: str) -> str | None:
    return next(
        (target.label for target in case.targets if target.id == target_id),
        None,
    )


def _format_target_name(target_id: str, target_label: Any) -> str:
    if not isinstance(target_label, str) or target_label == target_id:
        return target_id
    return f"{target_label} ({target_id})"


def _format_target_text(target_id: str, target_label: Any) -> Text:
    return Text(_format_target_name(target_id, target_label))


def _short(value: Any) -> str:
    text = repr(value)
    if len(text) > 80:
        return text[:77] + "..."
    return text


def _format_duration(duration_s: float) -> str:
    if duration_s < 60:
        return f"{duration_s:.1f}s"
    minutes, seconds = divmod(duration_s, 60)
    if minutes < 60:
        return f"{int(minutes)}m {seconds:.1f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {seconds:.1f}s"


def _format_evaluation_duration(duration_s: float) -> str:
    if duration_s < 0.01:
        return f"{duration_s * 1000:.2f}ms"
    if duration_s < 1:
        return f"{duration_s * 1000:.0f}ms"
    if duration_s < 10:
        return f"{duration_s:.2f}s"
    return _format_duration(duration_s)
