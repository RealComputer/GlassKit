from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from glasskit_ai.eval.models import EvalRunReport
from glasskit_ai.eval.report import print_run_summary


def test_print_run_summary_includes_formatted_duration() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    report = EvalRunReport(
        suite_path=Path("eval-suite"),
        case_names=[],
        results=[],
        gate_results=[],
        duration_s=125.5,
    )

    print_run_summary(report, console=console)

    assert "Duration: 2m 5.5s" in buffer.getvalue()
