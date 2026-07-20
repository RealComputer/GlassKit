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
from rich.text import Text

from .eval.checkpoints import (
    checkpoint_path_from_error,
    load_checkpoint,
)
from .eval.commands import format_command
from .eval.expectations import load_eval_directory
from .eval.models import EvalError, RunOptions, SeedIncompleteError, SeedOptions
from .eval.report import (
    ConsoleReporter,
    ConsoleSeedReporter,
    print_run_summary,
    print_sample_schedule,
    print_seed_summary,
    print_validation_report,
)
from .eval.review.documents import ReviewRepository
from .eval.review.server import create_review_server
from .eval.runner import (
    run_eval,
    run_options_from_invocation,
    validate_eval_directory,
)
from .eval.seeding import seed_eval, seed_options_from_invocation

app = typer.Typer(no_args_is_help=True)
eval_app = typer.Typer(no_args_is_help=True, help="Recorded-video eval tools.")
app.add_typer(eval_app, name="eval")

DEFAULT_EVAL_DIR = Path("eval")
DEFAULT_ADAPTER_CALLABLE = "create_evaluator"
ADAPTER_CONFIG_FILE_NAMES = ("adapter.yaml", "adapter.yml")


@eval_app.command("seed")
def eval_seed(
    adapter: Annotated[
        str | None,
        typer.Option(
            "--adapter",
            help=(
                "Labeling adapter in module/file:callable form. Defaults to "
                "adapter.py with create_evaluator in the eval dir."
            ),
        ),
    ] = None,
    adapter_command: Annotated[
        str | None,
        typer.Option(
            "--adapter-command",
            help=(
                "Command for an NDJSON labeling adapter, such as "
                "'node eval/adapter.js'."
            ),
        ),
    ] = None,
    eval_dir: Annotated[
        Path,
        typer.Option("--eval-dir", help="Eval directory."),
    ] = DEFAULT_EVAL_DIR,
    case: Annotated[
        str | None,
        typer.Option("--case", help="Only seed one case by filename or stem."),
    ] = None,
    target: Annotated[
        list[str] | None,
        typer.Option(
            "--target",
            help="Only seed this target id; repeat to select multiple targets.",
        ),
    ] = None,
    adapter_config: Annotated[
        Path | None,
        typer.Option(
            "--adapter-config",
            help=(
                "YAML or JSON config passed to the adapter. Defaults to "
                "adapter.yaml in the eval dir when present."
            ),
        ),
    ] = None,
    concurrency: Annotated[
        int,
        typer.Option(
            "--concurrency",
            min=1,
            help=(
                "Maximum concurrent per-sample evaluate calls; ignored when the "
                "adapter uses evaluate_many."
            ),
        ),
    ] = 1,
    replace: Annotated[
        bool,
        typer.Option(
            "--replace",
            help="Replace existing expectations in the selected scope too.",
        ),
    ] = False,
    keep_going: Annotated[
        bool,
        typer.Option(
            "--keep-going",
            help=(
                "Checkpoint adapter errors and continue; case YAML remains unchanged "
                "until every selected expectation succeeds."
            ),
        ),
    ] = False,
    resume: Annotated[
        Path | None,
        typer.Option(
            "--resume",
            help="Resume an incomplete seed checkpoint by path or checkpoint id.",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Print every proposed expectation."),
    ] = False,
) -> None:
    """Propose expectations for selected draft samples with an adapter."""

    console = Console()
    if resume is not None:
        _reject_seed_resume_overrides(
            adapter=adapter,
            adapter_command=adapter_command,
            case=case,
            target=target,
            adapter_config=adapter_config,
            concurrency=concurrency,
            replace=replace,
            keep_going=keep_going,
            verbose=verbose,
        )
        try:
            snapshot = load_checkpoint(eval_dir, resume, expected_kind="seed")
        except EvalError as error:
            raise typer.BadParameter(str(error), param_hint="--resume") from error
        options = seed_options_from_invocation(
            snapshot.invocation,
            checkpoint_path=snapshot.path,
        )
    else:
        if adapter is not None and adapter_command is not None:
            raise typer.BadParameter(
                "cannot be used with --adapter", param_hint="--adapter-command"
            )
        adapter_target = (
            None
            if adapter_command is not None
            else adapter or _default_adapter_target(eval_dir)
        )
        options = SeedOptions(
            eval_dir=eval_dir,
            adapter=adapter_target,
            adapter_command=adapter_command,
            case_filter=case,
            target_filter=_target_filter(target),
            adapter_config=_load_adapter_config(adapter_config, eval_dir),
            concurrency=concurrency,
            replace=replace,
            keep_going=keep_going,
            verbose=verbose,
        )
    reporter = ConsoleSeedReporter(verbose=options.verbose, console=console)
    try:
        report = asyncio.run(seed_eval(options, callbacks=reporter))
    except KeyboardInterrupt as error:
        _print_interruption(
            console,
            "Seeding interrupted",
            "seed",
            checkpoint_path_from_error(error) or _reporter_checkpoint_path(reporter),
        )
        raise typer.Exit(130) from error
    except SeedIncompleteError as error:
        _print_labeled_message(console, "Seed incomplete", str(error), style="red")
        _print_resume_hint(
            console,
            "seed",
            checkpoint_path_from_error(error) or _reporter_checkpoint_path(reporter),
        )
        raise typer.Exit(1) from error
    except EvalError as error:
        _print_labeled_message(
            console, "Could not seed expectations", str(error), style="red"
        )
        _print_resume_hint(
            console,
            "seed",
            checkpoint_path_from_error(error) or _reporter_checkpoint_path(reporter),
        )
        raise typer.Exit(2) from error
    finally:
        reporter.close()
    print_seed_summary(report, console=console)


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
    adapter_command: Annotated[
        str | None,
        typer.Option(
            "--adapter-command",
            help=(
                "Command for an NDJSON process adapter, such as 'node eval/adapter.js'."
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
        list[str] | None,
        typer.Option(
            "--target",
            help="Only run this target id; repeat to select multiple targets.",
        ),
    ] = None,
    from_time: Annotated[
        float | None,
        typer.Option(
            "--from",
            min=0.0,
            help=(
                "Only run samples at or after this time in seconds; requires --case."
            ),
        ),
    ] = None,
    until_time: Annotated[
        float | None,
        typer.Option(
            "--until",
            min=0.0,
            help=("Only run samples before this time in seconds; requires --case."),
        ),
    ] = None,
    adapter_config: Annotated[
        Path | None,
        typer.Option(
            "--adapter-config",
            help=(
                "YAML or JSON config passed to the adapter. Defaults to "
                "adapter.yaml in the eval dir when present."
            ),
        ),
    ] = None,
    concurrency: Annotated[
        int,
        typer.Option(
            "--concurrency",
            min=1,
            help=(
                "Maximum concurrent per-sample evaluate calls; ignored when the "
                "adapter uses evaluate_many."
            ),
        ),
    ] = 1,
    repeat: Annotated[
        int,
        typer.Option(
            "--repeat",
            min=1,
            help="Run the selected eval this many times as sequential trials.",
        ),
    ] = 1,
    min_pass_rate: Annotated[
        float | None,
        typer.Option(
            "--min-pass-rate",
            min=0.0,
            max=1.0,
            help="Per-trial pass-rate gate.",
        ),
    ] = None,
    min_target_pass_rate: Annotated[
        float | None,
        typer.Option(
            "--min-target-pass-rate",
            min=0.0,
            max=1.0,
            help="Uniform per-target pass-rate gate applied to every trial.",
        ),
    ] = None,
    max_failures: Annotated[
        int | None,
        typer.Option(
            "--max-failures",
            min=0,
            help="Per-trial maximum failed comparisons.",
        ),
    ] = None,
    max_flaky_samples: Annotated[
        int | None,
        typer.Option(
            "--max-flaky-samples",
            min=0,
            help=(
                "Maximum samples whose pass/fail/error status varies across trials; "
                "requires --repeat of at least 2."
            ),
        ),
    ] = None,
    keep_going: Annotated[
        bool,
        typer.Option(
            "--keep-going",
            help="Record adapter or comparison errors as results and continue.",
        ),
    ] = False,
    resume: Annotated[
        Path | None,
        typer.Option(
            "--resume",
            help="Resume an incomplete run checkpoint by path or checkpoint id.",
        ),
    ] = None,
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
                "writes to trial-specific directories under runs/failures in the "
                "eval dir."
            ),
        ),
    ] = None,
    save_failures: Annotated[
        bool,
        typer.Option(
            "--save-failures",
            help="Save failed or errored sample-attempt frames and result JSON.",
        ),
    ] = False,
    allow_empty: Annotated[
        bool,
        typer.Option("--allow-empty", help="Allow evals or cases with no samples."),
    ] = False,
) -> None:
    """Run selected samples and apply quality gates."""

    console = Console()
    if resume is not None:
        _reject_run_resume_overrides(
            adapter=adapter,
            adapter_command=adapter_command,
            case=case,
            target=target,
            from_time=from_time,
            until_time=until_time,
            adapter_config=adapter_config,
            concurrency=concurrency,
            repeat=repeat,
            min_pass_rate=min_pass_rate,
            min_target_pass_rate=min_target_pass_rate,
            max_failures=max_failures,
            max_flaky_samples=max_flaky_samples,
            keep_going=keep_going,
            output_json=output_json,
            artifacts_dir=artifacts_dir,
            save_failures=save_failures,
            allow_empty=allow_empty,
            verbose=verbose,
        )
        try:
            snapshot = load_checkpoint(eval_dir, resume, expected_kind="run")
        except EvalError as error:
            raise typer.BadParameter(str(error), param_hint="--resume") from error
        options = run_options_from_invocation(
            snapshot.invocation,
            checkpoint_path=snapshot.path,
        )
    else:
        _validate_sample_time_options(
            case=case,
            from_time=from_time,
            until_time=until_time,
        )
        if adapter is not None and adapter_command is not None:
            raise typer.BadParameter(
                "cannot be used with --adapter", param_hint="--adapter-command"
            )
        adapter_target = (
            None
            if adapter_command is not None
            else adapter or _default_adapter_target(eval_dir)
        )
        options = RunOptions(
            adapter=adapter_target,
            adapter_command=adapter_command,
            eval_dir=eval_dir,
            case_filter=case,
            target_filter=_target_filter(target),
            from_time_s=from_time,
            until_time_s=until_time,
            adapter_config=_load_adapter_config(adapter_config, eval_dir),
            concurrency=concurrency,
            repeat=repeat,
            min_pass_rate=min_pass_rate,
            min_target_pass_rate=min_target_pass_rate,
            max_failures=max_failures,
            max_flaky_samples=max_flaky_samples,
            keep_going=keep_going,
            verbose=verbose,
            output_json=output_json,
            artifacts_dir=artifacts_dir,
            save_failures=save_failures,
            allow_empty=allow_empty,
        )
    reporter = ConsoleReporter(verbose=options.verbose, console=console)
    try:
        report = asyncio.run(run_eval(options, callbacks=reporter))
    except KeyboardInterrupt as error:
        _print_interruption(
            console,
            "Eval interrupted",
            "run",
            checkpoint_path_from_error(error) or _reporter_checkpoint_path(reporter),
        )
        raise typer.Exit(130) from error
    except EvalError as error:
        _print_labeled_message(console, "Eval failed", str(error), style="red")
        _print_resume_hint(
            console,
            "run",
            checkpoint_path_from_error(error) or _reporter_checkpoint_path(reporter),
        )
        raise typer.Exit(2) from error
    finally:
        reporter.close()
    print_run_summary(report, console=console)
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
    adapter_command: Annotated[
        str | None,
        typer.Option(
            "--adapter-command",
            help="Optional NDJSON process adapter command to start and validate.",
        ),
    ] = None,
    case: Annotated[
        str | None,
        typer.Option("--case", help="Only validate one case by filename or stem."),
    ] = None,
    target: Annotated[
        list[str] | None,
        typer.Option(
            "--target",
            help="Only validate this target id; repeat to select multiple targets.",
        ),
    ] = None,
    adapter_config: Annotated[
        Path | None,
        typer.Option(
            "--adapter-config",
            help=(
                "YAML or JSON config passed to the adapter. Defaults to "
                "adapter.yaml in the eval dir when present."
            ),
        ),
    ] = None,
    allow_empty: Annotated[
        bool,
        typer.Option("--allow-empty", help="Allow evals or cases with no samples."),
    ] = False,
) -> None:
    """Validate selected eval structure without evaluating samples."""

    if adapter is not None and adapter_command is not None:
        raise typer.BadParameter(
            "cannot be used with --adapter", param_hint="--adapter-command"
        )
    options = RunOptions(
        adapter=adapter,
        adapter_command=adapter_command,
        eval_dir=eval_dir,
        case_filter=case,
        target_filter=_target_filter(target),
        adapter_config=_load_adapter_config(adapter_config, eval_dir),
        allow_empty=allow_empty,
    )
    report = asyncio.run(validate_eval_directory(options))
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
        list[str] | None,
        typer.Option(
            "--target",
            help="Only list this target id; repeat to select multiple targets.",
        ),
    ] = None,
    from_time: Annotated[
        float | None,
        typer.Option(
            "--from",
            min=0.0,
            help=(
                "Only list samples at or after this time in seconds; requires --case."
            ),
        ),
    ] = None,
    until_time: Annotated[
        float | None,
        typer.Option(
            "--until",
            min=0.0,
            help=("Only list samples before this time in seconds; requires --case."),
        ),
    ] = None,
    allow_empty: Annotated[
        bool,
        typer.Option("--allow-empty", help="Allow evals or cases with no samples."),
    ] = False,
) -> None:
    """List the expanded selected sample schedule."""

    _validate_sample_time_options(
        case=case,
        from_time=from_time,
        until_time=until_time,
    )
    try:
        loaded = load_eval_directory(
            eval_dir,
            case_filter=case,
            target_filter=_target_filter(target),
            from_time_s=from_time,
            until_time_s=until_time,
            allow_empty=allow_empty,
        )
    except EvalError as error:
        _print_labeled_message(
            Console(), "Could not list samples", str(error), style="red"
        )
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
                "the eval directory."
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
        _print_labeled_message(
            console, "Could not start review UI", str(error), style="red"
        )
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
            _print_labeled_message(
                console, "Could not open browser", str(error), style="yellow"
            )
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


def _validate_sample_time_options(
    *,
    case: str | None,
    from_time: float | None,
    until_time: float | None,
) -> None:
    if (from_time is not None or until_time is not None) and case is None:
        raise typer.BadParameter(
            "--from and --until require --case",
            param_hint="--from/--until",
        )
    for option, value in (("--from", from_time), ("--until", until_time)):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise typer.BadParameter(
                "must be a finite, nonnegative number",
                param_hint=option,
            )
    if from_time is not None and until_time is not None and from_time >= until_time:
        raise typer.BadParameter(
            "must be greater than --from",
            param_hint="--until",
        )


def _load_adapter_config(path: Path | None, eval_dir: Path) -> dict[str, Any]:
    if path is not None:
        return _load_config(path)

    expanded_eval_dir = eval_dir.expanduser()
    candidates = [
        expanded_eval_dir / name
        for name in ADAPTER_CONFIG_FILE_NAMES
        if (expanded_eval_dir / name).exists()
    ]
    if len(candidates) > 1:
        joined = ", ".join(str(candidate) for candidate in candidates)
        raise typer.BadParameter(
            f"multiple adapter config files found: {joined}; "
            "remove one or pass --adapter-config"
        )
    return _load_config(candidates[0] if candidates else None)


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


def _target_filter(targets: list[str] | None) -> tuple[str, ...] | None:
    return tuple(targets) if targets is not None else None


def _reject_seed_resume_overrides(
    *,
    adapter: str | None,
    adapter_command: str | None,
    case: str | None,
    target: list[str] | None,
    adapter_config: Path | None,
    concurrency: int,
    replace: bool,
    keep_going: bool,
    verbose: bool,
) -> None:
    if any(
        (
            adapter is not None,
            adapter_command is not None,
            case is not None,
            target is not None,
            adapter_config is not None,
            concurrency != 1,
            replace,
            keep_going,
            verbose,
        )
    ):
        raise typer.BadParameter(
            "restores the original adapter and seed options and cannot be combined "
            "with overrides",
            param_hint="--resume",
        )


def _reject_run_resume_overrides(
    *,
    adapter: str | None,
    adapter_command: str | None,
    case: str | None,
    target: list[str] | None,
    from_time: float | None,
    until_time: float | None,
    adapter_config: Path | None,
    concurrency: int,
    repeat: int,
    min_pass_rate: float | None,
    min_target_pass_rate: float | None,
    max_failures: int | None,
    max_flaky_samples: int | None,
    keep_going: bool,
    output_json: Path | None,
    artifacts_dir: Path | None,
    save_failures: bool,
    allow_empty: bool,
    verbose: bool,
) -> None:
    if any(
        (
            adapter is not None,
            adapter_command is not None,
            case is not None,
            target is not None,
            from_time is not None,
            until_time is not None,
            adapter_config is not None,
            concurrency != 1,
            repeat != 1,
            min_pass_rate is not None,
            min_target_pass_rate is not None,
            max_failures is not None,
            max_flaky_samples is not None,
            keep_going,
            output_json is not None,
            artifacts_dir is not None,
            save_failures,
            allow_empty,
            verbose,
        )
    ):
        raise typer.BadParameter(
            "restores the original adapter and run options and cannot be combined "
            "with overrides",
            param_hint="--resume",
        )


def _print_resume_hint(
    console: Console, command: str, checkpoint_path: Path | None
) -> None:
    if checkpoint_path is None:
        return
    console.print(f"Checkpoint: {checkpoint_path}", highlight=False)
    resume_command = format_command(
        ["glasskit", "eval", command, "--resume", str(checkpoint_path)]
    )
    console.print(f"Resume with `{resume_command}`.", highlight=False)


def _print_interruption(
    console: Console,
    label: str,
    command: str,
    checkpoint_path: Path | None,
) -> None:
    detail = (
        "progress was saved"
        if checkpoint_path is not None
        else "no reusable progress was saved"
    )
    _print_labeled_message(console, label, detail, style="red")
    _print_resume_hint(console, command, checkpoint_path)


def _reporter_checkpoint_path(reporter: Any) -> Path | None:
    value = getattr(reporter, "checkpoint_path", None)
    return value if isinstance(value, Path) else None


def _print_labeled_message(
    console: Console, label: str, message: str, *, style: str
) -> None:
    text = Text()
    text.append(label, style=style)
    text.append(": ")
    text.append(message)
    console.print(text, highlight=False)
