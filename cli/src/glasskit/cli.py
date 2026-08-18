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
from rich.default_styles import DEFAULT_STYLES
from rich.style import Style
from rich.text import Text

from . import __version__
from .eval.checkpoints import (
    checkpoint_path_from_error,
    load_checkpoint,
)
from .eval.cloud_video import (
    materialize_video,
    prune_video_cache,
    upload_video,
    video_cache_dir,
)
from .eval.commands import format_command
from .eval.expectations import load_eval_directory, load_video_stores
from .eval.frame_export import export_case_frames
from .eval.models import (
    EvalConfigError,
    EvalError,
    RunOptions,
    SeedIncompleteError,
    SeedOptions,
)
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


def _configure_rich_help_styles() -> None:
    """Keep inline Markdown code readable across terminal color palettes.

    Typer dims detailed help, while Rich defaults inline code to cyan on ANSI
    black. ANSI black is palette-specific rather than the terminal background.
    """
    DEFAULT_STYLES["markdown.code"] = Style(bold=True, dim=False)


_configure_rich_help_styles()

ROOT_EPILOG = """
Run `glasskit COMMAND --help` for a command's options and examples. When a command
lists subcommands, continue recursively; for example,
`glasskit eval video-store upload --help`.
"""

EVAL_HELP = """
Turn labeled moments in recorded videos into repeatable app evaluations. GlassKit
selects frames, passes them and target metadata to an app adapter, compares the
adapter's JSON-like observations with expectations, and applies optional quality
gates.
"""

EVAL_DETAILS = """
## Eval directory

Commands use `./eval` by default. The recommended layout is:

```text
eval/
  adapter.py       # Default Python adapter for seed and run
  adapter.yaml     # Optional object passed to the adapter
  config.yaml      # Optional eval-wide thresholds and video stores
  cases/
    task-01.yaml
```

Each case declares one video and one or more targets. A local video path is relative
to the case file. This is a complete case:

```yaml
video: task-01.mp4
targets:
  ready:
    samples:
    - at: 1.5
      expect: true
```

Use `at` for one time or a list of times. Use `range: [start, end]` for a half-open
range sampled every `every_s` seconds; the case default is `0.5`. An omitted
`expect` is a draft for `seed`; `expect: null` is a real expectation. An `ignore`
reason excludes a sample from decoding, adapter calls, metrics, and gates.
Overlapping or duplicate samples within one target are invalid, and expansion is
limited to 10,000 samples per case. A target's optional `config` mapping is passed
through to the adapter.

`field` selects a dot-separated observation path such as `result.matches`; numeric
parts index arrays. `compare.mode` may be `exact`, `numeric`, `json_subset`,
`set_equals`, `set_contains_any`, or `set_contains_all`. Numeric comparison uses
absolute difference and defaults to tolerance `0`. Without a mode, numbers use
`numeric` and other values use `exact`; exact comparison keeps booleans distinct
from numbers. Set modes treat arrays as JSON sets. `json_subset` recursively
requires expected keys and items, matching duplicate array items separately. Case
`sample_defaults` are overridden by target `sample_defaults`, then by the sample
block.

## Python adapter contract

`seed` and `run` default to `<eval-dir>/adapter.py:create_evaluator`. The callable
may be sync or async and may take no arguments or one factory context. A typical
adapter is:

```python
def create_evaluator(context):
    class Evaluator:
        async def evaluate(self, sample, target):
            return await app_observation(sample.image, target.config)
    return Evaluator()
```

The factory context has `eval_dir`, `config`, `artifacts_dir`, and `verbose`.
`sample` has `image` (a display-oriented RGB Pillow image), `timestamp_s`,
`frame_index`, `sample_index`, `video_path`, and `case_name`. `target` has `id`,
`index`, `label`, and `config`. Return `None`, a boolean, finite number, string,
array, or string-keyed object. An evaluator may instead implement
`evaluate_many(samples, target)` and return one observation per sample in order;
it takes precedence over `evaluate`. Optional `close()` and all evaluation methods
may be sync or async.
The adapter target may also be a direct function whose first two positional
parameter names are `image, target_id` or `sample, target`.

`adapter.yaml`, or an explicit `--adapter-config` YAML or JSON object, is available
as `context.config`. Config files do not expand environment variables; keep secrets
in the process environment.

Frames are selected by requested video time using the nearest decoded media
timestamp, with ties choosing the earlier frame. Display rotation is applied before
the image reaches the adapter.

## Command adapter protocol

`--adapter-command` starts the parsed argv directly, without a shell, in the
current working directory and environment. Stdin and stdout are UTF-8 NDJSON
protocol streams; write logs to stderr. Requests are
`{"id":N,"method":METHOD,"params":OBJECT}` and responses are either
`{"id":N,"result":VALUE}` or
`{"id":N,"error":{"message":"..."}}`. Concurrent requests may be answered in
any order by id.

The first method is `initialize`. Its params contain `protocolVersion: 1` and
`config: {evalDir, config, artifactsDir, verbose}`. Respond with
`{"protocolVersion":1,"capabilities":{"evaluate":true}}`, using
`evaluateMany` instead or as well when supported. `evaluate` params contain
`sample` and `target`; `evaluateMany` contains `samples` and `target`. Sample and
target names are the Python fields above in lower camel case. `sample.image` is
`{mimeType:"image/png", dataBase64, width, height}`. The result is one JSON value,
or an ordered array of values for `evaluateMany`. Reply successfully to `close`,
then exit. A notification `{"method":"cancel","params":{"id":N}}` may cancel an
in-flight request and has no response.

## Suggested workflow

Use `validate` to check cases and videos, `list-samples` to inspect expanded ranges,
`seed` or `review` to label drafts, and `run` to evaluate them. Run
`glasskit eval COMMAND --help` for each command's effects, exit codes, and examples.
`video-store` is another command group, so recurse through its `--help` too.
"""

VIDEO_STORE_HELP = """
Manage case videos stored in AWS S3, Cloudflare R2, or another S3-compatible object
store. Downloads are content-addressed and accepted only after their declared
SHA-256 verifies.
"""

VIDEO_STORE_DETAILS = """
Define stores in `<eval-dir>/config.yaml`:

```yaml
video_stores:
  team-videos:
    type: s3
    bucket: team-eval-videos
    region: us-east-1
    endpoint_url: https://optional-s3-endpoint.example
    access_key_id_env: EVAL_STORAGE_ACCESS_KEY_ID
    secret_access_key_env: EVAL_STORAGE_SECRET_ACCESS_KEY
```

Omit the endpoint for AWS S3. Omit custom credential names to use the standard AWS
credential chain. `public_base_url` enables unauthenticated HTTP downloads while
uploads still use S3 credentials. An uploaded case reference has this form:

```yaml
video:
  store: team-videos
  key: recordings/task-01.mp4
  sha256: 64-character-hex-digest
```

`run`, `seed`, `validate`, `export-frames`, and `review` download remote videos on
demand. `list-samples` validates references without downloading. Downloads use a
per-user cache outside the eval directory; set `GLASSKIT_EVAL_CACHE_DIR` to override
its location. Run `glasskit eval video-store COMMAND --help` for transfer and cache
details.
"""

SEED_HELP = """
Call an adapter to propose expectations for selected draft samples. By default only
samples that omit `expect` are evaluated; explicit `null` is already labeled and
ignored samples are never seeded. If a sample has `field`, the selected field rather
than the complete observation becomes its expectation.
"""

SEED_DETAILS = """
## Effects and recovery

`seed` mutates selected case YAML. Existing expectations are preserved unless
`--replace` is set. Candidate files are validated only after every selected
expectation succeeds. Immediately before each atomic replacement, seed compares the
current source with the version it loaded and refuses the write when they differ.
Treat generated expectations as proposals and inspect them with `review`.

Successful adapter results are checkpointed under `<eval-dir>/runs/checkpoints/`.
With `--keep-going`, errors are retained and other samples continue, but case YAML
is unchanged until a later resume completes everything. `--resume` restores the
original adapter, filters, config, concurrency, and seed options and cannot be
combined with overrides; `--eval-dir` may be used to locate a checkpoint id. Resume
reuses successes and attempts each error or unfinished sample once. Checkpoints can
contain adapter config and observations and should be treated as sensitive,
disposable state.

Exit `0` means seeding completed or nothing needed seeding; `1` means
`--keep-going` left expectations incomplete; `2` means the operation aborted; `130`
means it was interrupted. When reusable work exists, the error output prints an
exact resume command.

## Examples

```sh
glasskit eval seed --case task-01 --target ready
glasskit eval seed --case task-01 --replace --keep-going --concurrency 4
glasskit eval seed --resume CHECKPOINT_ID
```
"""

RUN_HELP = """
Evaluate selected declared samples and apply quality gates. No correctness threshold
is enabled by default: failed comparisons are reported but do not by themselves
make the command fail. Configure a CLI or YAML gate for CI.
"""

RUN_DETAILS = r"""
## Selection and gates

`--at`, `--from`, and `--until` filter samples already declared in the selected
case; they do not create samples at arbitrary video times. `--from` is inclusive and
`--until` is exclusive. Gates apply only to selected, non-ignored results and apply
independently to every trial from `--repeat`.

Eval-wide and case thresholds use this shape in `config.yaml` or a case file:

```yaml
thresholds:
  min_pass_rate: 0.9
  max_failures: 3
  per_target:
    ready:
      min_pass_rate: 0.95
```

CLI `--min-pass-rate` and `--max-failures` override their eval-wide values; setting
either suppresses case-level gates. `--min-target-pass-rate` replaces eval-wide
per-target gates with one uniform selected-target gate. `--max-flaky-samples`
measures status variation across trials, not correctness, so combine it with a
correctness gate when both matter. Adapter or comparison errors always fail the
automatic error gate when `--keep-going` records them.

## Output and recovery

`--output-json` writes an object containing overall `success`, counts, per-trial
`results` and `gates`, cross-trial `stability`, and checkpoint metadata. Each result
includes the complete `observed` value and the `observed_value` selected by `field`.
`--save-failures` writes a JPEG and result JSON for every failed or errored attempt,
grouped under `failures/trial-NNN/` below the chosen artifacts directory.

Completed results are checkpointed under `<eval-dir>/runs/checkpoints/`.
`--resume` restores every original run option and cannot be combined with overrides;
`--eval-dir` may locate a checkpoint id. Resume retries only adapter-error and
unfinished slots, not completed passes, failures, ignores, or comparison errors.
Checkpoints can contain adapter config and observations and should be treated as
sensitive, disposable state.

Exit `0` means every configured gate passed; `1` means execution completed but a
gate failed; `2` means setup or runtime aborted the run; `130` means it was
interrupted. When reusable work exists, error output prints an exact resume command.

## Examples

```sh
glasskit eval run --case task-01 --target ready --verbose
glasskit eval run --min-pass-rate 0.9 --max-failures 3 \
  --output-json eval/runs/results.json
glasskit eval run --repeat 3 --max-flaky-samples 0 --min-pass-rate 0.9
```
"""

VALIDATE_HELP = """
Validate selected case schemas, expanded samples, expectations, video readability,
and sample times without evaluating samples. Remote videos are downloaded and
verified when needed.
"""

VALIDATE_DETAILS = """
Draft non-ignored samples are invalid in the selected scope. Without `--adapter` or
`--adapter-command`, only the eval and videos are checked; the default adapter is not
loaded. When an adapter is explicitly selected, `validate` constructs and closes it
but does not call an evaluation method or verify observation values.

Exit `0` means validation passed; `1` means validation issues were reported. CLI
usage errors exit `2`.

```sh
glasskit eval validate
glasskit eval validate --case task-01 --adapter eval/adapter.py:create_evaluator
```
"""

LIST_SAMPLES_HELP = """
Print the expanded selected sample schedule, including case, target, requested time,
expectation, field, comparison mode, ignore reason, and source block. It parses cloud
references but does not download or decode videos and does not load an adapter.
"""

LIST_SAMPLES_DETAILS = """
Ranges are half-open: `range: [1, 2]` with `every_s: 0.5` produces `1` and `1.5`.
Time options filter already-declared samples; `--from` is inclusive and `--until` is
exclusive. Non-ignored drafts are rejected in the selected scope.

Exit `0` means the schedule was listed; loading or validation errors exit `2`.

```sh
glasskit eval list-samples --case task-01
glasskit eval list-samples --case task-01 --target ready --from 4 --until 8
```
"""

EXPORT_FRAMES_HELP = """
Export display-oriented lossless PNG frames at arbitrary video times. Unlike
`run --at`, these times do not need to be declared eval samples. Remote videos are
downloaded and verified when needed.
"""

EXPORT_FRAMES_DETAILS = """
Each requested time uses the same nearest-decoded-frame selection as evaluation,
with ties choosing the earlier frame. Duplicate times are exported once. The default
destination is `<eval-dir>/runs/frames/<case>/`; filenames are `at-<seconds>s.png`
and an existing file with the same name is replaced.

Exit `0` means all paths printed were exported; errors exit `2`.

```sh
glasskit eval export-frames --case task-01 --at 7.5 --at 8
glasskit eval export-frames --case task-01 --at 7.5 --output-dir /tmp/frames
```
"""

REVIEW_HELP = """
Start a loopback browser UI for reviewing and editing timed expectations. Case,
target, and time options choose the initial view; they do not filter which cases are
available. Remote videos are downloaded and verified when needed.
"""

REVIEW_DETAILS = """
The server listens on `127.0.0.1`, runs until interrupted, and writes edits directly
to case YAML. Use `--no-open` in headless environments and open the printed URL
yourself. Port `0` chooses a free port.

Startup or configuration errors exit `2`; Ctrl-C stops the server normally.

```sh
glasskit eval review
glasskit eval review --case task-01 --target ready --time 7.5 --no-open
```
"""

VIDEO_PULL_HELP = """
Download every remote video referenced by the selected cases, verify its declared
SHA-256, and print each distinct cached path. Draft and empty cases are allowed.
"""

VIDEO_PULL_DETAILS = """
Existing verified cache entries are reused. If no selected case uses a cloud video,
the command reports that and succeeds. Transfer or configuration errors exit `2`.

```sh
glasskit eval video-store pull
glasskit eval video-store pull --case task-01
```
"""

VIDEO_UPLOAD_HELP = """
Upload a supported local video to a named S3-compatible store and print a complete
YAML `video` block for a case file. Supported suffixes are `.mp4`, `.mov`, `.m4v`,
`.webm`, and `.mkv`.
"""

VIDEO_UPLOAD_DETAILS = r"""
Without `--key`, the immutable object key is `<sha256><extension>`. An existing
object found during the preflight check is reused only when its size and SHA-256
metadata match; otherwise the upload is refused. Successful uploads are verified
afterward. The named store and its credentials come from `<eval-dir>/config.yaml`.
Transfer or configuration errors exit `2`.

```sh
glasskit eval video-store upload task-01.mp4 --store team-videos
glasskit eval video-store upload task-01.mp4 --store team-videos \
  --key tasks/task-01.mp4
```
"""

VIDEO_PRUNE_HELP = """
Prune the per-user downloaded-video cache. By default only stale incomplete
transfers and locks are removed; `--all` also removes verified videos, which will be
downloaded again when needed.
"""

VIDEO_PRUNE_DETAILS = """
This cache is shared across eval directories. The command prints the number and size
of removed files plus the resolved cache path. Cache errors exit `2`.

```sh
glasskit eval video-store prune-cache
glasskit eval video-store prune-cache --all
```
"""


app = typer.Typer(
    no_args_is_help=True,
    epilog=ROOT_EPILOG,
    rich_markup_mode="markdown",
)
eval_app = typer.Typer(
    no_args_is_help=True,
    help=f"{EVAL_HELP}\n\n{EVAL_DETAILS}",
    short_help="Recorded-video eval tools.",
    rich_markup_mode="markdown",
)
video_store_app = typer.Typer(
    no_args_is_help=True,
    help=f"{VIDEO_STORE_HELP}\n\n{VIDEO_STORE_DETAILS}",
    short_help="Manage videos backed by cloud object storage.",
    rich_markup_mode="markdown",
)
app.add_typer(eval_app, name="eval")
eval_app.add_typer(video_store_app, name="video-store")

DEFAULT_EVAL_DIR = Path("eval")
DEFAULT_ADAPTER_CALLABLE = "create_evaluator"
ADAPTER_CONFIG_FILE_NAMES = ("adapter.yaml", "adapter.yml")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"glasskit {__version__}")
        raise typer.Exit()


@app.callback()
def glasskit(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = None,
) -> None:
    """GlassKit tools for smart-glasses apps."""


@eval_app.command(
    "seed",
    help=f"{SEED_HELP}\n\n{SEED_DETAILS}",
    short_help="Propose expectations for selected draft samples with an adapter.",
)
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
                "Direct command for an NDJSON protocol-v1 labeling adapter, such "
                "as 'node eval/adapter.js'; mutually exclusive with --adapter."
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
            help=(
                "Resume by checkpoint path or id, restoring all original options; "
                "cannot be combined with overrides."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help=(
                "Print every proposed expectation and pass verbose=true to the adapter."
            ),
        ),
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


@eval_app.command(
    "run",
    help=f"{RUN_HELP}\n\n{RUN_DETAILS}",
    short_help="Run selected samples and apply quality gates.",
)
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
                "Direct command for an NDJSON protocol-v1 adapter, such as 'node "
                "eval/adapter.js'; mutually exclusive with --adapter."
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
    at: Annotated[
        list[float] | None,
        typer.Option(
            "--at",
            min=0.0,
            help=(
                "Only run samples at this exact declared time in seconds; repeat "
                "to select multiple times; requires --case; cannot be combined "
                "with --from or --until."
            ),
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
            help=(
                "Per-trial selected-result pass-rate gate; overrides the eval-wide "
                "value and suppresses case-level gates."
            ),
        ),
    ] = None,
    min_target_pass_rate: Annotated[
        float | None,
        typer.Option(
            "--min-target-pass-rate",
            min=0.0,
            max=1.0,
            help=(
                "Uniform selected-target pass-rate gate applied to every trial; "
                "replaces eval-wide per-target gates."
            ),
        ),
    ] = None,
    max_failures: Annotated[
        int | None,
        typer.Option(
            "--max-failures",
            min=0,
            help=(
                "Per-trial maximum failed comparisons; overrides the eval-wide "
                "value and suppresses case-level gates."
            ),
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
            help=(
                "Resume by checkpoint path or id, restoring all original options; "
                "cannot be combined with overrides."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Print every sample result and pass verbose=true to the adapter.",
        ),
    ] = False,
    output_json: Annotated[
        Path | None,
        typer.Option(
            "--output-json",
            help=(
                "Write complete machine-readable results, gates, stability, and "
                "checkpoint metadata as JSON."
            ),
        ),
    ] = None,
    artifacts_dir: Annotated[
        Path | None,
        typer.Option(
            "--artifacts-dir",
            help=(
                "Directory for generated artifacts. When omitted, --save-failures "
                "writes to trial-specific directories under runs/failures in the "
                "eval dir. Also passed to the adapter factory."
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
            at=at,
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
            at=at,
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
            at_times_s=tuple(at) if at is not None else None,
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


@eval_app.command(
    "validate",
    help=f"{VALIDATE_HELP}\n\n{VALIDATE_DETAILS}",
    short_help="Validate selected eval structure without evaluating samples.",
)
def eval_validate(
    eval_dir: Annotated[
        Path, typer.Option("--eval-dir", help="Eval directory.")
    ] = DEFAULT_EVAL_DIR,
    adapter: Annotated[
        str | None,
        typer.Option(
            "--adapter",
            help=(
                "Optional module/file:callable adapter to construct and close; the "
                "default adapter is not checked when this is omitted."
            ),
        ),
    ] = None,
    adapter_command: Annotated[
        str | None,
        typer.Option(
            "--adapter-command",
            help=(
                "Optional direct NDJSON protocol-v1 adapter command to start and "
                "close; mutually exclusive with --adapter."
            ),
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


@eval_app.command(
    "list-samples",
    help=f"{LIST_SAMPLES_HELP}\n\n{LIST_SAMPLES_DETAILS}",
    short_help="List the expanded selected sample schedule.",
)
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
    at: Annotated[
        list[float] | None,
        typer.Option(
            "--at",
            min=0.0,
            help=(
                "Only list samples at this exact declared time in seconds; repeat "
                "to select multiple times; requires --case; cannot be combined "
                "with --from or --until."
            ),
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
        at=at,
        from_time=from_time,
        until_time=until_time,
    )
    try:
        loaded = load_eval_directory(
            eval_dir,
            case_filter=case,
            target_filter=_target_filter(target),
            at_times_s=tuple(at) if at is not None else None,
            from_time_s=from_time,
            until_time_s=until_time,
            allow_empty=allow_empty,
            materialize_videos=False,
        )
    except EvalError as error:
        _print_labeled_message(
            Console(), "Could not list samples", str(error), style="red"
        )
        raise typer.Exit(2) from error
    print_sample_schedule(loaded)


@video_store_app.command(
    "pull",
    help=f"{VIDEO_PULL_HELP}\n\n{VIDEO_PULL_DETAILS}",
    short_help="Download and verify remote videos into the local cache.",
)
def eval_video_store_pull(
    eval_dir: Annotated[
        Path, typer.Option("--eval-dir", help="Eval directory.")
    ] = DEFAULT_EVAL_DIR,
    case: Annotated[
        str | None,
        typer.Option("--case", help="Only download one case by filename or stem."),
    ] = None,
) -> None:
    """Download and verify remote videos into the local cache."""

    try:
        loaded = load_eval_directory(
            eval_dir,
            case_filter=case,
            allow_empty=True,
            allow_draft=True,
            materialize_videos=False,
        )
        stores = load_video_stores(loaded.path)
        remote_cases = [case for case in loaded.cases if case.remote_video is not None]
        paths: list[Path] = []
        seen: set[Path] = set()
        for loaded_case in remote_cases:
            remote = loaded_case.remote_video
            assert remote is not None
            path = materialize_video(remote, stores[remote.store])
            if path not in seen:
                seen.add(path)
                paths.append(path)
    except EvalError as error:
        _print_labeled_message(
            Console(), "Could not pull cloud videos", str(error), style="red"
        )
        raise typer.Exit(2) from error
    if not remote_cases:
        typer.echo("No cloud videos are referenced by the selected cases.")
        return
    for path in paths:
        typer.echo(path)


@video_store_app.command(
    "upload",
    help=f"{VIDEO_UPLOAD_HELP}\n\n{VIDEO_UPLOAD_DETAILS}",
    short_help="Upload a local video and print its case-file reference.",
)
def eval_video_store_upload(
    source: Annotated[
        Path,
        typer.Argument(help="Local video file to upload."),
    ],
    store_name: Annotated[
        str,
        typer.Option("--store", help="Named video store from eval/config.yaml."),
    ],
    eval_dir: Annotated[
        Path, typer.Option("--eval-dir", help="Eval directory.")
    ] = DEFAULT_EVAL_DIR,
    key: Annotated[
        str | None,
        typer.Option(
            "--key",
            help=("Object key. Defaults to an immutable key derived from the SHA-256."),
        ),
    ] = None,
) -> None:
    """Upload a local video and print its case-file reference."""

    try:
        stores = load_video_stores(eval_dir)
        store = stores.get(store_name)
        if store is None:
            available = ", ".join(repr(name) for name in sorted(stores)) or "none"
            raise EvalConfigError(
                f"unknown video store {store_name!r}; configured stores: {available}"
            )
        result = upload_video(source, store, key=key)
    except EvalError as error:
        _print_labeled_message(
            Console(), "Could not upload cloud video", str(error), style="red"
        )
        raise typer.Exit(2) from error
    if result.already_existed:
        typer.echo("Object already exists with matching size and SHA-256.")
    typer.echo(
        yaml.safe_dump(
            {
                "video": {
                    "store": result.store,
                    "key": result.key,
                    "sha256": result.sha256,
                }
            },
            sort_keys=False,
        ).rstrip()
    )


@video_store_app.command(
    "prune-cache",
    help=f"{VIDEO_PRUNE_HELP}\n\n{VIDEO_PRUNE_DETAILS}",
    short_help="Remove incomplete transfers, or the complete downloaded-video cache.",
)
def eval_video_store_prune_cache(
    all_files: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Remove verified videos too; they will be downloaded again when used.",
        ),
    ] = False,
) -> None:
    """Remove incomplete transfers, or the complete downloaded-video cache."""

    try:
        count, size = prune_video_cache(remove_verified=all_files)
    except EvalError as error:
        _print_labeled_message(
            Console(), "Could not prune downloaded-video cache", str(error), style="red"
        )
        raise typer.Exit(2) from error
    typer.echo(
        f"Removed {count} cached file{'s' if count != 1 else ''} "
        f"({_format_byte_count(size)}) from {video_cache_dir()}"
    )


@eval_app.command(
    "export-frames",
    help=f"{EXPORT_FRAMES_HELP}\n\n{EXPORT_FRAMES_DETAILS}",
    short_help="Export eval-decoded frames at selected case times.",
)
def eval_export_frames(
    case: Annotated[
        str,
        typer.Option("--case", help="Case filename or stem containing the video."),
    ],
    at: Annotated[
        list[float],
        typer.Option(
            "--at",
            min=0.0,
            help="Frame time in seconds; repeat to export multiple frames.",
        ),
    ],
    eval_dir: Annotated[
        Path, typer.Option("--eval-dir", help="Eval directory.")
    ] = DEFAULT_EVAL_DIR,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help=(
                "Destination directory; defaults below the eval directory at "
                "runs/frames/."
            ),
        ),
    ] = None,
) -> None:
    """Export the eval-decoded frames at selected case times."""

    try:
        paths = export_case_frames(
            eval_dir,
            case_selector=case,
            timestamps_s=at,
            output_dir=output_dir,
        )
    except EvalError as error:
        _print_labeled_message(
            Console(), "Could not export frames", str(error), style="red"
        )
        raise typer.Exit(2) from error
    for path in paths:
        typer.echo(path)


@eval_app.command(
    "review",
    help=f"{REVIEW_HELP}\n\n{REVIEW_DETAILS}",
    short_help="Review and edit timed expectations in a local browser UI.",
)
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
    at: list[float] | None,
    from_time: float | None,
    until_time: float | None,
) -> None:
    if (
        at is not None or from_time is not None or until_time is not None
    ) and case is None:
        if at is not None:
            option = "--at"
        elif from_time is not None:
            option = "--from"
        else:
            option = "--until"
        raise typer.BadParameter(
            "requires --case",
            param_hint=option,
        )
    if at is not None and (from_time is not None or until_time is not None):
        raise typer.BadParameter(
            "cannot be combined with --from or --until",
            param_hint="--at",
        )
    for value in at or ():
        if not math.isfinite(value) or value < 0:
            raise typer.BadParameter(
                "must be a finite, nonnegative number",
                param_hint="--at",
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


def _format_byte_count(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


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
    at: list[float] | None,
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
            at is not None,
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
