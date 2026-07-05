from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console

from .eval.expectations import load_eval_suite
from .eval.init_case import init_eval_case
from .eval.models import EvalError, RunOptions
from .eval.report import (
    ConsoleReporter,
    print_run_summary,
    print_sample_schedule,
    print_validation_report,
)
from .eval.runner import run_eval, validate_eval_suite

app = typer.Typer(no_args_is_help=True)
eval_app = typer.Typer(no_args_is_help=True, help="Recorded-video eval tools.")
app.add_typer(eval_app, name="eval")

DEFAULT_EVAL_DIR = Path("eval")
DEFAULT_ADAPTER = "eval/adapter.py:create_evaluator"


@eval_app.command("run")
def eval_run(
    adapter: Annotated[
        str,
        typer.Option(
            "--adapter", help="Adapter target, e.g. eval/adapter.py:create_evaluator."
        ),
    ] = DEFAULT_ADAPTER,
    eval_dir: Annotated[
        Path,
        typer.Option("--eval-dir", help="Eval directory."),
    ] = DEFAULT_EVAL_DIR,
    case: Annotated[
        str | None,
        typer.Option("--case", help="Only run one case by filename stem."),
    ] = None,
    adapter_config: Annotated[
        Path | None,
        typer.Option(
            "--adapter-config", help="YAML or JSON config passed to the adapter."
        ),
    ] = None,
    min_pass_rate: Annotated[
        float | None,
        typer.Option("--min-pass-rate", min=0.0, max=1.0),
    ] = None,
    min_target_pass_rate: Annotated[
        float | None,
        typer.Option("--min-target-pass-rate", min=0.0, max=1.0),
    ] = None,
    max_failures: Annotated[
        int | None,
        typer.Option("--max-failures", min=0),
    ] = None,
    keep_going: Annotated[
        bool,
        typer.Option("--keep-going", help="Record adapter errors and continue."),
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
        typer.Option("--artifacts-dir", help="Directory for generated artifacts."),
    ] = None,
    save_failures: Annotated[
        bool,
        typer.Option("--save-failures", help="Save failed sample frames and metadata."),
    ] = False,
    max_failures_to_print: Annotated[
        int,
        typer.Option("--max-failures-to-print", min=0),
    ] = 20,
    allow_empty: Annotated[
        bool,
        typer.Option("--allow-empty", help="Allow evals or cases with no samples."),
    ] = False,
) -> None:
    console = Console()
    options = RunOptions(
        adapter=adapter,
        eval_dir=eval_dir,
        case_filter=case,
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
        typer.Option("--case", help="Only validate one case by filename stem."),
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
        typer.Option("--case", help="Only list one case by filename stem."),
    ] = None,
    allow_empty: Annotated[
        bool,
        typer.Option("--allow-empty", help="Allow evals or cases with no samples."),
    ] = False,
) -> None:
    try:
        loaded = load_eval_suite(eval_dir, case_filter=case, allow_empty=allow_empty)
    except EvalError as error:
        Console().print(f"[red]Could not list samples[/red]: {error}")
        raise typer.Exit(2) from error
    print_sample_schedule(loaded)


@eval_app.command("init-case")
def eval_init_case(
    case: Annotated[str, typer.Option("--case", help="Case filename stem.")],
    video: Annotated[Path, typer.Option("--video", help="Source video file.")],
    target: Annotated[str, typer.Option("--target", help="Initial target id.")],
    eval_dir: Annotated[
        Path, typer.Option("--eval-dir", help="Eval directory.")
    ] = DEFAULT_EVAL_DIR,
    label: Annotated[
        str | None,
        typer.Option("--label", help="Optional label for the initial target."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite case YAML and copied video."),
    ] = False,
) -> None:
    try:
        result = init_eval_case(
            eval_dir=eval_dir,
            case_name=case,
            source_video=video,
            target_id=target,
            target_label=label,
            force=force,
        )
    except EvalError as error:
        Console().print(f"[red]Could not initialize case[/red]: {error}")
        raise typer.Exit(2) from error
    Console().print(f"Created case: {result.case_path}")
    Console().print(f"Video: {result.video_path}")
    Console().print(f"Eval: {result.eval_dir}")


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
