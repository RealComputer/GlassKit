from __future__ import annotations

import asyncio
import json
import math
import webbrowser
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

import typer
import yaml
from rich.console import Console

from .eval.expectations import load_eval_suite
from .eval.models import EvalError, RunOptions
from .eval.report import (
    ConsoleReporter,
    print_run_summary,
    print_sample_schedule,
    print_validation_report,
)
from .eval.review.documents import ReviewRepository
from .eval.review.server import create_review_server
from .eval.runner import run_eval, validate_eval_suite

app = typer.Typer(no_args_is_help=True)
eval_app = typer.Typer(no_args_is_help=True, help="Recorded-video eval tools.")
app.add_typer(eval_app, name="eval")

DEFAULT_EVAL_DIR = Path("eval")
DEFAULT_ADAPTER_CALLABLE = "create_evaluator"


@eval_app.command("run")
def eval_run(
    adapter: Annotated[
        str | None,
        typer.Option(
            "--adapter",
            help=(
                "Adapter target in module/file:callable form. Defaults to "
                "adapter.py with create_evaluator in the eval dir."
            ),
        ),
    ] = None,
    eval_dir: Annotated[
        Path,
        typer.Option("--eval-dir", help="Eval directory."),
    ] = DEFAULT_EVAL_DIR,
    case: Annotated[
        str | None,
        typer.Option("--case", help="Only run one case by filename or stem."),
    ] = None,
    target: Annotated[
        str | None,
        typer.Option("--target", help="Only run one target id from selected cases."),
    ] = None,
    adapter_config: Annotated[
        Path | None,
        typer.Option(
            "--adapter-config", help="YAML or JSON config passed to the adapter."
        ),
    ] = None,
    min_pass_rate: Annotated[
        float | None,
        typer.Option(
            "--min-pass-rate",
            min=0.0,
            max=1.0,
            help="Run-level pass-rate gate.",
        ),
    ] = None,
    min_target_pass_rate: Annotated[
        float | None,
        typer.Option(
            "--min-target-pass-rate",
            min=0.0,
            max=1.0,
            help="Uniform per-target pass-rate gate.",
        ),
    ] = None,
    max_failures: Annotated[
        int | None,
        typer.Option(
            "--max-failures",
            min=0,
            help="Run-level maximum failed comparisons.",
        ),
    ] = None,
    keep_going: Annotated[
        bool,
        typer.Option(
            "--keep-going",
            help="Record adapter or comparison errors as results and continue.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Print every sample result."),
    ] = False,
    output_json: Annotated[
        Path | None,
        typer.Option("--output-json", help="Write machine-readable results JSON."),
    ] = None,
    artifacts_dir: Annotated[
        Path | None,
        typer.Option(
            "--artifacts-dir",
            help=(
                "Directory for generated artifacts. When omitted, --save-failures "
                "writes under runs/failures in the eval dir."
            ),
        ),
    ] = None,
    save_failures: Annotated[
        bool,
        typer.Option(
            "--save-failures",
            help="Save failed or errored sample frames and per-result JSON.",
        ),
    ] = False,
    max_failures_to_print: Annotated[
        int,
        typer.Option(
            "--max-failures-to-print",
            min=0,
            help="Maximum non-passing results printed in the failures table.",
        ),
    ] = 20,
    allow_empty: Annotated[
        bool,
        typer.Option("--allow-empty", help="Allow evals or cases with no samples."),
    ] = False,
) -> None:
    console = Console()
    adapter_target = adapter or _default_adapter_target(eval_dir)
    options = RunOptions(
        adapter=adapter_target,
        eval_dir=eval_dir,
        case_filter=case,
        target_filter=target,
        adapter_config=_load_config(adapter_config),
        min_pass_rate=min_pass_rate,
        min_target_pass_rate=min_target_pass_rate,
        max_failures=max_failures,
        keep_going=keep_going,
        verbose=verbose,
        output_json=output_json,
        artifacts_dir=artifacts_dir,
        save_failures=save_failures,
        max_failures_to_print=max_failures_to_print,
        allow_empty=allow_empty,
    )
    reporter = ConsoleReporter(verbose=verbose, console=console)
    try:
        report = asyncio.run(run_eval(options, callbacks=reporter))
    except EvalError as error:
        console.print(f"[red]Eval failed[/red]: {error}")
        raise typer.Exit(2) from error
    print_run_summary(
        report,
        max_failures_to_print=max_failures_to_print,
        console=console,
    )
    raise typer.Exit(0 if report.success else 1)


@eval_app.command("validate")
def eval_validate(
    eval_dir: Annotated[
        Path, typer.Option("--eval-dir", help="Eval directory.")
    ] = DEFAULT_EVAL_DIR,
    adapter: Annotated[
        str | None,
        typer.Option(
            "--adapter", help="Optional adapter target to import and construct."
        ),
    ] = None,
    case: Annotated[
        str | None,
        typer.Option("--case", help="Only validate one case by filename or stem."),
    ] = None,
    target: Annotated[
        str | None,
        typer.Option(
            "--target", help="Only validate one target id from selected cases."
        ),
    ] = None,
    adapter_config: Annotated[
        Path | None,
        typer.Option(
            "--adapter-config", help="YAML or JSON config passed to the adapter."
        ),
    ] = None,
    allow_empty: Annotated[
        bool,
        typer.Option("--allow-empty", help="Allow evals or cases with no samples."),
    ] = False,
) -> None:
    options = RunOptions(
        adapter=adapter,
        eval_dir=eval_dir,
        case_filter=case,
        target_filter=target,
        adapter_config=_load_config(adapter_config),
        allow_empty=allow_empty,
    )
    report = asyncio.run(validate_eval_suite(options))
    print_validation_report(report)
    raise typer.Exit(0 if report.ok else 1)


@eval_app.command("list-samples")
def eval_list_samples(
    eval_dir: Annotated[
        Path, typer.Option("--eval-dir", help="Eval directory.")
    ] = DEFAULT_EVAL_DIR,
    case: Annotated[
        str | None,
        typer.Option("--case", help="Only list one case by filename or stem."),
    ] = None,
    target: Annotated[
        str | None,
        typer.Option("--target", help="Only list one target id from selected cases."),
    ] = None,
    allow_empty: Annotated[
        bool,
        typer.Option("--allow-empty", help="Allow evals or cases with no samples."),
    ] = False,
) -> None:
    try:
        loaded = load_eval_suite(
            eval_dir,
            case_filter=case,
            target_filter=target,
            allow_empty=allow_empty,
        )
    except EvalError as error:
        Console().print(f"[red]Could not list samples[/red]: {error}")
        raise typer.Exit(2) from error
    print_sample_schedule(loaded)


@eval_app.command("review")
def eval_review(
    eval_dir: Annotated[
        Path,
        typer.Option("--eval-dir", help="Eval directory."),
    ] = DEFAULT_EVAL_DIR,
    case: Annotated[
        str | None,
        typer.Option(
            "--case",
            help=(
                "Initially open this case by filename or stem; all cases remain "
                "available."
            ),
        ),
    ] = None,
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            help=(
                "Initially focus this target; requires --case and does not filter "
                "the suite."
            ),
        ),
    ] = None,
    time_s: Annotated[
        float | None,
        typer.Option(
            "--time",
            help="Initially seek to this nonnegative time; requires --case.",
        ),
    ] = None,
    port: Annotated[
        int,
        typer.Option(
            "--port",
            min=0,
            max=65535,
            help="Local port; 0 chooses an available port.",
        ),
    ] = 0,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="Print the URL without opening a browser."),
    ] = False,
) -> None:
    """Review and edit timed expectations in a local browser UI."""

    if target is not None and case is None:
        raise typer.BadParameter("--target requires --case", param_hint="--target")
    if time_s is not None and case is None:
        raise typer.BadParameter("--time requires --case", param_hint="--time")
    if time_s is not None and (not math.isfinite(time_s) or time_s < 0):
        raise typer.BadParameter(
            "must be a finite, nonnegative number", param_hint="--time"
        )

    console = Console()
    server = None
    try:
        repository = ReviewRepository(eval_dir)
        case_id = repository.resolve_case_selector(case) if case is not None else None
        target_id = (
            repository.validate_target_selector(case_id, target)
            if case_id is not None and target is not None
            else None
        )
        server = create_review_server(
            eval_dir,
            port=port,
            repository=repository,
        )
    except (EvalError, OSError, ValueError) as error:
        console.print(f"[red]Could not start review UI[/red]: {error}")
        raise typer.Exit(2) from error

    query: dict[str, str | float] = {}
    if case_id is not None:
        query["case"] = case_id
    if target_id is not None:
        query["target"] = target_id
    if time_s is not None:
        query["time"] = time_s
    url = server.url + (f"?{urlencode(query)}" if query else "")
    console.print(f"Review UI: [link={url}]{url}[/link]")

    if not no_open:
        try:
            opened = webbrowser.open(url)
        except Exception as error:  # Browser launch is intentionally nonfatal.
            console.print(f"[yellow]Could not open browser[/yellow]: {error}")
        else:
            if not opened:
                console.print(
                    "[yellow]Could not open browser automatically; "
                    "use the URL above.[/yellow]"
                )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    finally:
        server.server_close()


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise typer.BadParameter(f"could not read adapter config: {error}") from error
    try:
        if path.suffix.lower() == ".json":
            raw = json.loads(text)
        else:
            raw = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise typer.BadParameter(f"invalid adapter config: {error}") from error
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise typer.BadParameter("adapter config must contain an object")
    return raw


def _default_adapter_target(eval_dir: Path) -> str:
    adapter_path = eval_dir / "adapter.py"
    return f"{adapter_path.as_posix()}:{DEFAULT_ADAPTER_CALLABLE}"
