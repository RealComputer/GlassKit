from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from .commands import format_command
from .expectations import format_sample_schedule
from .models import (
    EvalCase,
    EvalDirectory,
    EvalRunReport,
    SampleExpectation,
    SampleResult,
    SampleStability,
    SeededExpectation,
    SeedReport,
    ValidationReport,
)


class _TargetProgress:
    def __init__(
        self, *, console: Console, unit: str, show_progress: bool = True
    ) -> None:
        self.console = console
        self.unit = unit
        self.enabled = (
            show_progress and console.is_terminal and not console.is_dumb_terminal
        )
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def start(self, total: int) -> None:
        self.stop()
        if not self.enabled or total <= 0:
            return
        progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.completed:.0f}/{task.total:.0f} " + self.unit),
            TextColumn("·"),
            TimeElapsedColumn(),
            TextColumn("elapsed"),
            console=self.console,
            refresh_per_second=4,
            transient=True,
        )
        task_id = progress.add_task("", total=total)
        self._progress = progress
        self._task_id = task_id
        progress.start()

    def advance(self) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.advance(self._task_id)

    def stop(self) -> None:
        if self._progress is not None:
            self._progress.stop()
        self._progress = None
        self._task_id = None


class ConsoleReporter:
    def __init__(
        self,
        *,
        verbose: bool = False,
        console: Console | None = None,
        show_progress: bool = True,
    ) -> None:
        self.verbose = verbose
        self.console = console or Console()
        self._trial_index = 1
        self._trial_count = 1
        self.checkpoint_path: Path | None = None
        self._target_progress = _TargetProgress(
            console=self.console,
            unit="samples",
            show_progress=show_progress,
        )

    def on_checkpoint(self, path: Path) -> None:
        self.checkpoint_path = path

    def on_trial_start(self, trial_index: int, trial_count: int) -> None:
        self._target_progress.stop()
        self._trial_index = trial_index
        self._trial_count = trial_count
        if trial_count > 1:
            self.console.print(
                f"\n[bold]Trial[/bold] {trial_index}/{trial_count}", highlight=False
            )

    def on_case_start(self, case: EvalCase, sample_count: int) -> None:
        self._target_progress.stop()
        self.console.print(
            f"[bold]Case[/bold] {case.name} "
            f"({sample_count} samples, video={_case_video_name(case)})",
            highlight=False,
        )

    def on_target_start(
        self, case: EvalCase, target_id: str, sample_count: int
    ) -> None:
        self._target_progress.stop()
        target_label = _target_label_for_case(case, target_id)
        target_name = escape(_format_target_name(target_id, target_label))
        self.console.print(
            f"  target {target_name}: {sample_count} samples",
            highlight=False,
        )
        self._target_progress.start(sample_count)

    def on_result(self, result: SampleResult) -> None:
        self._target_progress.advance()
        if result.status == "passed" and not self.verbose:
            return
        style = {
            "passed": "green",
            "ignored": "yellow",
        }.get(result.status, "red")
        line = Text("    ")
        if self._trial_count > 1:
            line.append(f"[{self._trial_index}/{self._trial_count}] ")
        line.append(result.status.upper(), style=style)
        line.append(
            f" {_format_target_name(result.target_id, result.target_label)} "
            f"@{result.timestamp_s:g}s "
            f"expected={_short(result.expected)} "
            f"observed={_short(result.observed_value)} "
            f"reason={result.reason}"
        )
        self.console.print(line, highlight=False)

    def close(self) -> None:
        self._target_progress.stop()


class ConsoleSeedReporter:
    def __init__(
        self,
        *,
        verbose: bool = False,
        console: Console | None = None,
        show_progress: bool = True,
    ) -> None:
        self.verbose = verbose
        self.console = console or Console()
        self.checkpoint_path: Path | None = None
        self._target_progress = _TargetProgress(
            console=self.console,
            unit="expectations",
            show_progress=show_progress,
        )

    def on_checkpoint(self, path: Path) -> None:
        self.checkpoint_path = path

    def on_case_start(self, case: EvalCase, sample_count: int) -> None:
        self._target_progress.stop()
        self.console.print(
            f"[bold]Case[/bold] {case.name} "
            f"({sample_count} expectations, video={_case_video_name(case)})",
            highlight=False,
        )

    def on_target_start(
        self, case: EvalCase, target_id: str, sample_count: int
    ) -> None:
        self._target_progress.stop()
        target_label = _target_label_for_case(case, target_id)
        target_name = escape(_format_target_name(target_id, target_label))
        self.console.print(
            f"  target {target_name}: {sample_count} expectations",
            highlight=False,
        )
        self._target_progress.start(sample_count)

    def on_result(self, result: SeededExpectation) -> None:
        self._target_progress.advance()
        if not self.verbose:
            return
        sample = result.sample
        line = Text("    ")
        line.append("SEEDED", style="green")
        line.append(
            f" {_format_target_name(sample.target_id, sample.target_label)} "
            f"@{sample.timestamp_s:g}s expect={_short(result.expected)}"
        )
        self.console.print(line, highlight=False)

    def on_error(self, sample: SampleExpectation, error: Exception) -> None:
        self._target_progress.advance()
        line = Text("    ")
        line.append("ERROR", style="red")
        line.append(
            f" {_format_target_name(sample.target_id, sample.target_label)} "
            f"@{sample.timestamp_s:g}s reason={error}"
        )
        self.console.print(line, highlight=False)

    def close(self) -> None:
        self._target_progress.stop()


def print_seed_summary(report: SeedReport, *, console: Console | None = None) -> None:
    console = console or Console()
    console.print(f"\n[bold]Seed[/bold]: {report.eval_dir}", highlight=False)
    if report.seeded_count == 0:
        console.print(
            f"Nothing to seed; {report.preserved_count} existing expectations "
            "were preserved.",
            highlight=False,
        )
        return
    console.print(f"Cases updated: {len(report.case_names)}", highlight=False)
    console.print(
        f"Expectations: {report.seeded_count} proposed, "
        f"{report.preserved_count} preserved",
        highlight=False,
    )
    console.print(f"Duration: {_format_duration(report.duration_s)}", highlight=False)
    for path in report.directory_sync_warnings:
        console.print(
            f"[yellow]Warning:[/yellow] replaced {path}, but syncing its directory "
            "failed.",
            highlight=False,
        )
    review_argv = ["glasskit", "eval", "review", "--eval-dir", str(report.eval_dir)]
    if len(report.case_names) == 1:
        review_argv.extend(("--case", report.case_names[0]))
    review_command = format_command(review_argv)
    console.print(
        f"Review the proposed expectations with `{review_command}`.",
        highlight=False,
    )


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
        message = Text()
        message.append("Validation passed", style="green")
        message.append(f": {eval_directory_name} ({sample_count} samples)")
        console.print(message, highlight=False)
        return
    console.print(Text("Validation failed", style="red"), highlight=False)
    for issue in report.issues:
        message = Text("- ")
        if issue.path:
            message.append(f"{issue.path}: ")
        message.append(issue.message)
        console.print(message, highlight=False)


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
    console: Console | None = None,
) -> None:
    console = console or Console()
    console.print(f"\n[bold]Eval[/bold]: {report.eval_dir}", highlight=False)
    console.print(f"Cases: {len(report.case_names)}", highlight=False)

    if report.repeat_count == 1:
        _print_single_run_summary(report, console)
    else:
        _print_repeated_run_summary(report, console)
    if report.resumable_error_count and report.checkpoint_path is not None:
        error_label = "error" if report.resumable_error_count == 1 else "errors"
        console.print(
            f"{report.resumable_error_count} adapter {error_label} can be retried "
            "without rerunning completed samples.",
            highlight=False,
        )
        console.print(f"Checkpoint: {report.checkpoint_path}", highlight=False)
        resume_command = format_command(
            ["glasskit", "eval", "run", "--resume", str(report.checkpoint_path)]
        )
        console.print(f"Resume with `{resume_command}`.", highlight=False)


def _print_single_run_summary(report: EvalRunReport, console: Console) -> None:
    trial = report.trials[0]
    console.print(
        "Samples: "
        f"{trial.evaluated_count} evaluated, "
        f"{trial.passed_count} passed, "
        f"{trial.failed_count} failed, "
        f"{trial.error_count} errors, "
        f"{trial.ignored_count} ignored",
        highlight=False,
    )
    console.print(f"Pass rate: {trial.pass_rate:.1%}", highlight=False)
    _print_timing_summary(report, console, item_label="sample")
    _print_single_run_failed_gates(report, console)
    _print_single_run_target_table(report, console)


def _print_repeated_run_summary(report: EvalRunReport, console: Console) -> None:
    console.print(
        f"Trials: {report.repeat_count} total, "
        f"{report.successful_trial_count} passed gates, "
        f"{report.repeat_count - report.successful_trial_count} failed gates",
        highlight=False,
    )
    console.print(
        "Samples: "
        f"{report.evaluated_sample_count} evaluated per trial, "
        f"{report.ignored_sample_count} ignored",
        highlight=False,
    )
    console.print(
        "Attempts: "
        f"{report.evaluated_attempt_count} evaluated, "
        f"{report.passed_attempt_count} passed, "
        f"{report.failed_attempt_count} failed, "
        f"{report.error_attempt_count} errors",
        highlight=False,
    )
    console.print(
        "Trial pass rate (min / mean / max): "
        f"{report.minimum_trial_pass_rate:.1%} / "
        f"{report.mean_trial_pass_rate:.1%} / "
        f"{report.maximum_trial_pass_rate:.1%}",
        highlight=False,
    )
    console.print(
        "Stability: "
        f"{report.consistently_passed_sample_count} consistently passed, "
        f"{report.consistently_failed_sample_count} consistently failed, "
        f"{report.flaky_sample_count} flaky, "
        f"{report.error_sample_count} with errors",
        highlight=False,
    )
    _print_timing_summary(report, console, item_label="attempt")

    trial_table = Table(title="By trial")
    trial_table.add_column("Trial", justify="right")
    trial_table.add_column("Pass rate", justify="right")
    trial_table.add_column("Passed", justify="right")
    trial_table.add_column("Failed", justify="right")
    trial_table.add_column("Errors", justify="right")
    trial_table.add_column("Gates")
    trial_table.add_column("Duration", justify="right")
    for trial in report.trials:
        trial_table.add_row(
            str(trial.index),
            f"{trial.pass_rate:.1%}",
            str(trial.passed_count),
            str(trial.failed_count),
            str(trial.error_count),
            "passed" if trial.success else "failed",
            _format_duration(trial.duration_s),
        )
    console.print(trial_table)

    _print_repeated_run_failed_gates(report, console)
    _print_repeated_run_target_table(report, console)

    notable_samples = [
        sample
        for sample in report.stability
        if sample.flaky or sample.consistently_failed or sample.has_errors
    ]
    if notable_samples:
        stability_table = Table(title="Unstable and failing samples")
        stability_table.add_column("Case")
        stability_table.add_column("Target")
        stability_table.add_column("Time", justify="right")
        stability_table.add_column("Outcomes")
        stability_table.add_column("Finding")
        for sample in notable_samples:
            stability_table.add_row(
                sample.case_name,
                _format_target_text(sample.target_id, sample.target_label),
                f"{sample.timestamp_s:g}s",
                "/".join(_status_abbreviation(status) for status in sample.statuses),
                _stability_finding(sample),
            )
        console.print(stability_table)


def _print_timing_summary(
    report: EvalRunReport, console: Console, *, item_label: str
) -> None:
    console.print(f"Duration: {_format_duration(report.duration_s)}", highlight=False)
    if report.average_evaluation_duration_s is not None:
        timing_label = _summary_timing_label(report.evaluation_timing_mode)
        console.print(
            f"{timing_label}: "
            f"{_format_evaluation_duration(report.average_evaluation_duration_s)}"
            f"/{item_label}",
            highlight=False,
        )
        console.print(
            f"Throughput: {report.throughput_attempts_per_s:.2f} {item_label}s/s",
            highlight=False,
        )


def _print_single_run_failed_gates(report: EvalRunReport, console: Console) -> None:
    failed_gates = [
        gate
        for trial in report.trials
        for gate in trial.gate_results
        if not gate.passed
    ]
    failed_gates.extend(gate for gate in report.gate_results if not gate.passed)
    if not failed_gates:
        return

    gate_table = Table(title="Failed gates")
    gate_table.add_column("Gate")
    gate_table.add_column("Detail")
    for gate in failed_gates:
        gate_table.add_row(gate.name, gate.message)
    console.print(gate_table)


def _print_repeated_run_failed_gates(report: EvalRunReport, console: Console) -> None:
    failed_gates = [
        (f"Trial {trial.index}", gate)
        for trial in report.trials
        for gate in trial.gate_results
        if not gate.passed
    ]
    failed_gates.extend(
        ("Stability", gate) for gate in report.gate_results if not gate.passed
    )
    if failed_gates:
        gate_table = Table(title="Failed gates")
        gate_table.add_column("Scope")
        gate_table.add_column("Gate")
        gate_table.add_column("Detail")
        for scope, gate in failed_gates:
            gate_table.add_row(
                scope,
                gate.name,
                gate.message,
            )
        console.print(gate_table)


def _print_single_run_target_table(report: EvalRunReport, console: Console) -> None:
    target_table = Table(title="By target")
    target_table.add_column("Target", no_wrap=True)
    target_table.add_column("Pass rate", justify="right")
    target_table.add_column("Passed", justify="right")
    target_table.add_column("Failed", justify="right")
    target_table.add_column("Errors", justify="right")
    target_table.add_column("Ignored", justify="right")
    show_timing = report.average_evaluation_duration_s is not None
    if show_timing:
        target_table.add_column(
            _target_timing_column(report.evaluation_timing_mode), justify="right"
        )
    for target_id, target_results in _group_results_by_target(
        report.trials[0].results
    ).items():
        evaluated = [result for result in target_results if result.status != "ignored"]
        passed = sum(result.status == "passed" for result in evaluated)
        pass_rate = passed / len(evaluated) if evaluated else 0.0
        target_label = _first_result_target_label(target_results)
        row = [
            _format_target_text(target_id, target_label),
            f"{pass_rate:.1%}",
            str(passed),
            str(sum(result.status == "failed" for result in evaluated)),
            str(sum(result.status == "error" for result in evaluated)),
            str(sum(result.status == "ignored" for result in target_results)),
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


def _print_repeated_run_target_table(report: EvalRunReport, console: Console) -> None:
    target_table = Table(title="By target")
    target_table.add_column("Target", no_wrap=True)
    target_table.add_column("Pass min / mean / max", justify="right")
    target_table.add_column("Samples", justify="right")
    target_table.add_column("Pass all", justify="right")
    target_table.add_column("Fail all", justify="right")
    target_table.add_column("Flaky", justify="right")
    target_table.add_column("Errors", justify="right")
    for target_id, target_stability in _group_stability_by_target(
        report.stability
    ).items():
        pass_rates = _target_trial_pass_rates(report, target_id)
        evaluated = sum(not sample.ignored for sample in target_stability)
        target_label = _first_stability_target_label(target_stability)
        row = [
            _format_target_text(target_id, target_label),
            _format_pass_rate_range(pass_rates),
            str(evaluated),
            str(sum(sample.consistently_passed for sample in target_stability)),
            str(sum(sample.consistently_failed for sample in target_stability)),
            str(sum(sample.flaky for sample in target_stability)),
            str(sum(sample.has_errors for sample in target_stability)),
        ]
        target_table.add_row(*row)
    console.print(target_table)


def _group_results_by_target(
    results: list[SampleResult],
) -> dict[str, list[SampleResult]]:
    grouped: dict[str, list[SampleResult]] = defaultdict(list)
    for result in results:
        grouped[result.target_id].append(result)
    return dict(sorted(grouped.items()))


def _first_result_target_label(results: list[SampleResult]) -> str | None:
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


def _group_stability_by_target(
    stability: list[SampleStability],
) -> dict[str, list[SampleStability]]:
    grouped: dict[str, list[SampleStability]] = defaultdict(list)
    for sample in stability:
        grouped[sample.target_id].append(sample)
    return dict(sorted(grouped.items()))


def _first_stability_target_label(samples: list[SampleStability]) -> str | None:
    return next(
        (sample.target_label for sample in samples if sample.target_label), None
    )


def _target_trial_pass_rates(report: EvalRunReport, target_id: str) -> list[float]:
    pass_rates: list[float] = []
    for trial in report.trials:
        results = [result for result in trial.results if result.target_id == target_id]
        evaluated = [result for result in results if result.status != "ignored"]
        passed = sum(result.status == "passed" for result in evaluated)
        pass_rates.append(passed / len(evaluated) if evaluated else 0.0)
    return pass_rates


def _format_pass_rate_range(pass_rates: list[float]) -> str:
    if not pass_rates:
        return "n/a"
    mean = sum(pass_rates) / len(pass_rates)
    return f"{min(pass_rates) * 100:.1f}/{mean * 100:.1f}/{max(pass_rates) * 100:.1f}%"


def _status_abbreviation(status: str) -> str:
    return {
        "passed": "P",
        "failed": "F",
        "error": "E",
        "ignored": "I",
    }[status]


def _stability_finding(sample: SampleStability) -> str:
    findings: list[str] = []
    if sample.flaky:
        findings.append("flaky")
    if sample.consistently_failed:
        findings.append("failed every trial")
    if sample.has_errors:
        findings.append("adapter/comparison errors")
    return ", ".join(findings)


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


def _case_video_name(case: EvalCase) -> str:
    if case.remote_video is not None:
        return case.remote_video.display_name
    return case.video_path.name


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
