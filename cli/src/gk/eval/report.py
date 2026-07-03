from __future__ import annotations

from collections import defaultdict
from typing import Any

from rich.console import Console
from rich.table import Table

from .expectations import format_sample_schedule
from .models import EvalCase, EvalRunReport, EvalSuite, SampleResult, ValidationReport


class ConsoleReporter:
    def __init__(
        self, *, verbose: bool = False, console: Console | None = None
    ) -> None:
        self.verbose = verbose
        self.console = console or Console()

    def on_case_start(self, case: EvalCase, sample_count: int) -> None:
        self.console.print(
            f"[bold]Case[/bold] {case.name} "
            f"({sample_count} samples, video={case.video_path.name})"
        )

    def on_target_start(
        self, case: EvalCase, target_id: str, sample_count: int
    ) -> None:
        self.console.print(f"  target {target_id}: {sample_count} samples")

    def on_result(self, result: SampleResult) -> None:
        if result.status == "passed" and not self.verbose:
            return
        style = "green" if result.status == "passed" else "red"
        self.console.print(
            f"    [{style}]{result.status.upper()}[/{style}] "
            f"{result.target_id} @{result.timestamp_s:g}s "
            f"expected={_short(result.expected)} "
            f"observed={_short(result.observed_value)} "
            f"reason={result.reason}"
        )


def print_validation_report(
    report: ValidationReport, console: Console | None = None
) -> None:
    console = console or Console()
    if report.ok:
        suite_name = str(report.suite.path) if report.suite is not None else "<none>"
        sample_count = len(report.suite.samples) if report.suite is not None else 0
        console.print(
            f"[green]Validation passed[/green]: {suite_name} ({sample_count} samples)"
        )
        return
    console.print("[red]Validation failed[/red]")
    for issue in report.issues:
        location = f"{issue.path}: " if issue.path else ""
        console.print(f"- {location}{issue.message}")


def print_sample_schedule(suite: EvalSuite, console: Console | None = None) -> None:
    console = console or Console()
    table = Table(title=f"Samples: {suite.path}")
    for column in ("Case", "Target", "Time", "Expected", "Mode", "Field", "Source"):
        table.add_column(column)
    for row in format_sample_schedule(suite):
        table.add_row(
            str(row["case"]),
            str(row["target"]),
            f"{row['timestamp_s']:g}s",
            _short(row["expected"]),
            str(row["mode"] or ""),
            str(row["field"] or ""),
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
    console.print(f"\n[bold]Eval suite[/bold]: {report.suite_path}")
    console.print(f"Cases: {len(report.case_names)}")
    console.print(
        "Samples: "
        f"{report.evaluated_count} evaluated, "
        f"{report.passed_count} passed, "
        f"{report.failed_count} failed, "
        f"{report.error_count} errors"
    )
    console.print(f"Pass rate: {report.pass_rate:.1%} ({status})")

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
    target_table.add_column("Total", justify="right")
    for target_id, target_results in _group_by_target(report.results).items():
        passed = sum(1 for result in target_results if result.status == "passed")
        total = len(target_results)
        pass_rate = passed / total if total else 0.0
        target_table.add_row(target_id, f"{pass_rate:.1%}", str(passed), str(total))
    console.print(target_table)

    failures = [result for result in report.results if result.status != "passed"]
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
                result.target_id,
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


def _short(value: Any) -> str:
    text = repr(value)
    if len(text) > 80:
        return text[:77] + "..."
    return text
