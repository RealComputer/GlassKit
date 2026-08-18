# GlassKit Eval

GlassKit Eval turns recorded video into repeatable evals for apps that make decisions from images. Label the moments that matter, connect your app through a language-agnostic adapter, and rerun the same checks locally or in CI.

The eval loop is not tied to glasses or a particular model provider. It works for robotics, camera automation, video-analysis pipelines, multimodal model features, and other systems that can evaluate a sampled frame and return a JSON-like observation.

Use GlassKit Eval through the `glasskit eval` command group. This is its user manual; for contributor implementation notes, see [AGENTS.md](https://github.com/RealComputer/GlassKit/blob/main/cli/AGENTS.md).

Contents: [Why Use This?](#why-use-this) · [How It Works](#how-it-works) · [Installation](#installation) · [Quickstart](#quickstart) · [Core Concepts](#core-concepts) · [Common Workflows](#common-workflows) · [Eval Directory Layout](#eval-directory-layout) · [Cloud-stored Videos](#cloud-stored-videos) · [Case File Reference](#case-file-reference) · [Comparison Reference](#comparison-reference) · [Adapter Reference](#adapter-reference) · [Command Reference](#command-reference) · [Configuration](#configuration) · [Environment Variables](#environment-variables) · [Output Formats](#output-formats) · [Exit Codes](#exit-codes) · [Support](#support)

## Why Use This?

Vision-based apps often turn camera input into a structured decision: whether a workflow step is complete, which objects are present, what state a scene is in, or what action should happen next. Recreating those scenes by hand for every prompt, model, or app logic change is slow and makes regressions difficult to reproduce.

With `glasskit eval`, you provide a recording, label expected outputs at selected moments, and replay the same checks whenever the app changes. The adapter boundary lets the eval exercise existing application logic regardless of its implementation language, while quality gates turn the results into a useful local or CI signal.

GlassKit Eval is a good fit when your behavior can be tested from sampled video frames and expressed as JSON-like outputs. It is intentionally frame-oriented; apps that require continuous video, audio, or other sensor streams may need an adapter that reconstructs that context.

## How It Works

Every eval command is a view of one pipeline:

```text
case file ─▶ sample schedule ─▶ decoded frames ─▶ adapter ─▶ observations
                                                                  │
       exit code ◀─ quality gates ◀─ report ◀─ compare vs expect ◀┘
```

1. A case file names a video and declares samples — single `at` timestamps or `range` blocks expanded every `every_s` seconds — with the expected JSON-like value at each one.
2. `glasskit eval run` checks the eval structure, videos, and sample times, expands the schedule, and decodes the frame nearest each scheduled timestamp.
3. Each frame goes to your adapter, which runs your app's logic and returns a JSON-like observation.
4. The CLI extracts the configured `field` from the observation, if any, and compares the value against the sample's `expect` using the sample's comparison settings, recording a pass, fail, or error for that sample.
5. Results are printed as tables and optionally written as a JSON report, and any configured quality gates turn them into the run's exit code — the CI signal.

The labeling commands work on the same pipeline: `seed` sends draft samples through the adapter and writes the results back as proposed `expect` values instead of comparing them, and `review` opens a browser UI for checking and editing labels against the video.

## Installation

The Python package is `glasskit.ai`; it provides the `glasskit` console command. The package requires Python 3.12 or newer and is designed to run with `uv`.

Add it to your app repo's dev dependencies:

```sh
uv add --dev glasskit.ai
uv run glasskit --help
```

Or run it once without adding the dependency:

```sh
uv run --with glasskit.ai glasskit --help
```

The `uv run ...` examples below assume the package has been added to your project. If you use the one-off form, replace `uv run` with `uv run --with glasskit.ai`.

## Quickstart

Start in your app repository. Any recording that is at least a few seconds long works for this walkthrough. This example copies an MP4 recording into `eval/cases/` so the case file can reference it by filename; [Eval Directory Layout](#eval-directory-layout) lists the supported formats.

Create the eval directory and write a case file that points at the recording:

```sh
mkdir -p eval/cases
cp path/to/any-recording.mp4 eval/cases/task-01.mp4
cat > eval/cases/task-01.yaml <<'YAML'
video: task-01.mp4
targets:
  step_1:
    samples:
    - range: [0.0, 3.0]
      expect: true
YAML
```

Create `eval/adapter.py` with a placeholder evaluator so you can verify that the eval wiring works before connecting a model pipeline:

```python
class Evaluator:
    async def evaluate(self, sample, target):
        return True


def create_evaluator(config):
    return Evaluator()
```

Run the eval:

```sh
uv run glasskit eval run
```

Expected result: `run` prints case progress, a summary, and a per-target table.

Recordings do not have to live inside the repo; [Eval Directory Layout](#eval-directory-layout) shows how to reference a shared `recordings/` directory, and [Cloud-stored Videos](#cloud-stored-videos) covers recordings too large to keep locally.

## Core Concepts

An eval directory is a collection of draft or runnable cases. By default, `glasskit eval` uses `eval/` in the current working directory.

A case file is one YAML file under `<eval-dir>/cases/`. The case name is the filename stem.

A video is declared by each case with `video:`. It can be a local path resolved relative to the case file or an object in a named cloud video store.

A target is one thing the adapter should evaluate, such as `step_1`, `ready_state`, or `detected_objects`.

A sample is one timestamp, or one timestamp expanded from a range. A runnable, non-ignored sample has an expected JSON-like value. A draft sample omits `expect` until `glasskit eval seed` proposes one or you add one manually; `expect: null` is a real expectation and is not a draft. Ignored samples may omit `expect` because they are not evaluated.

An adapter is your Python bridge from the CLI to your app's logic. The CLI decodes frames and calls the adapter; the adapter returns observations.

A gate is a quality bar, such as a minimum pass rate or maximum failure count, that turns eval results into a pass/fail signal for CI. Because model-based checks may not always reach 100%, gates let you choose the right bar for your app.

## Common Workflows

### Create a New Eval Case

Goal: create the required directory structure and a case file in `eval/` from an existing recording.

Commands:

```sh
mkdir -p eval/cases
cat > eval/cases/task-02.yaml <<'YAML'
video: ../../../recordings/task-02.mov
description: Replace this note with what task-02 should cover.
sampling:
  every_s: 0.5
targets:
  step_2:
    samples:
    - range: [0.0, 6.0]
      expect: false
    - range: [6.0, 12.0]
      expect: true
YAML
```

Expected result: `eval/cases/task-02.yaml` points to `task-02.mov` in the sibling `recordings/` directory and labels the expected value before and after the six-second mark.

Note: If you prefer colocated fixtures, put the recording in `eval/cases/` and set `video:` to the filename, such as `task-02.mov`.

### Seed Draft Expectations

Hand-labeling is the clearest way to start. When a case has many samples, you can instead omit `expect` and ask an adapter to propose the missing values:

```sh
uv run --env-file .env glasskit eval seed --case task-02
uv run glasskit eval review --case task-02
```

`seed` uses the same adapter as `run` by default, fills only omitted expectations, and preserves existing labels. Use `--adapter` or `--adapter-command` to label with a different adapter, and use `--case` or `--target` to narrow the work. Treat generated values as proposals and review them before relying on the eval.

### Review and Correct Expectations in the Browser

Goal: make recorded-video expectations faster to verify and correct.

Without the review UI, verifying expectations means juggling a media player and YAML editor while matching timestamps by hand. The review UI puts the video, expanded sample schedule, and editing controls in one place, making corrections faster and less error-prone.

Command:

```sh
uv run glasskit eval review --eval-dir eval
```

To jump directly to a failure reported by a separate eval run, include its case, target, and timestamp:

```sh
uv run glasskit eval review --eval-dir eval --case task-01 --target step_1 --time 7.4
```

The command opens a local browser UI where you can compare labeled moments with their source video and add, move, edit, or delete samples. Changes are saved automatically to the case file.

### Run One Case While Debugging

Goal: run a focused eval and print every sample result.

Command:

```sh
uv run glasskit eval run --case task-01 --target step_1 --verbose --keep-going --save-failures --output-json eval/runs/results.json --artifacts-dir eval/runs/artifacts
```

Expected output: focused case and target progress, every selected sample result, a final summary, and a per-target table.

Note: `--keep-going` records adapter evaluation errors and comparison errors as sample results instead of aborting on the first sample error. Every completed adapter result is also checkpointed, so when there is reusable progress the printed `glasskit eval run --resume ...` command can retry adapter errors without rerunning completed samples. `--save-failures` writes JPEG frames and per-result JSON for failed or errored samples. Treat `eval/runs/` as disposable output and add it to your app repo's `.gitignore` if you keep generated eval reports out of source control.

### Measure Nondeterministic Stability

Goal: run the same selected eval three times and identify samples whose outcomes vary.

With `--repeat N`, GlassKit Eval executes the same selected sample schedule `N` times. Each complete repetition is called a trial, and each evaluation of a sample within a trial is an attempt.

Command:

```sh
uv run --env-file .env glasskit eval run --concurrency 2 --repeat 3 --max-flaky-samples 0 --output-json eval/runs/repeated-results.json
```

Expected output: three sequential trial progress sections, a per-trial quality table, minimum/mean/maximum trial pass rates, per-target stability, and a table of flaky or consistently failing samples. The command constructs and closes a fresh evaluator for every trial. `--concurrency 2` still permits at most two individual evaluations in flight because trials themselves are never run concurrently.

Every trial uses the same filters and selected schedule. Quality gates such as `--min-pass-rate` apply independently to each trial, and the run fails if any trial fails one; results are never pooled before applying a quality gate. `--max-flaky-samples 0` checks only whether sample statuses vary across trials, so combine it with a correctness gate such as `--min-pass-rate 0.9` when both stability and quality should affect the exit code. Repeating an eval multiplies its adapter work and provider cost by the repeat count.

### Enforce CI Quality Gates

Goal: make the command fail when quality drops below your threshold.

Command:

```sh
uv run glasskit eval run --min-pass-rate 0.9 --min-target-pass-rate 0.85 --max-failures 3 --output-json eval/runs/results.json
```

Expected behavior: the process exits `0` when every configured quality gate passes, `1` when the eval completed but one or more gates failed, and `2` for setup or runtime errors that abort the run.

Note: Threshold defaults are intentionally unset. Without `--min-pass-rate`, `--min-target-pass-rate`, `--max-failures`, or YAML thresholds, failed comparisons are visible in the report but do not fail the command. Always configure a gate for CI.

### Use an Adapter Config File

Goal: pass runtime settings to your adapter without putting them in case files.

Save portable adapter settings in `eval/adapter.yaml`; GlassKit discovers this file automatically:

```sh
uv run --env-file .env glasskit eval run
```

Example `eval/adapter.yaml`:

```yaml
api_url: https://example.test/v1
model: vision-checker
jpeg_quality: 90
```

Use `--adapter-config PATH` to load a different YAML or JSON object instead. GlassKit does not expand environment variables inside adapter config files. Read secrets from environment variables in your adapter.

## Eval Directory Layout

A typical layout keeps the eval directory and adapter code in the app repo while storing recordings outside the repo:

```text
recordings/
  task-01.mp4
  task-02.mp4
your-app-repo/
  eval/
    adapter.py
    adapter.yaml # Optional adapter config file
    config.yaml # Optional thresholds and cloud video stores
    cases/
      task-01.yaml # Case file
      task-02.yaml
```

You can also keep videos next to the case file and reference them with a local filename such as `video: task-01.mp4`. Local paths are the simplest setup.

The `video:` path in the case file is resolved relative to that file. If recordings are too large to keep locally or share through Git, use a cloud video store as described below.

The adapter config file is optional and must be named `adapter.yaml` for automatic discovery. The eval config file is also optional and supports eval-level `thresholds` and named `video_stores`; it must be named `config.yaml`. Case files must live directly under `cases/` and use the `.yaml` suffix. Supported video suffixes are `.mp4`, `.mov`, `.m4v`, `.webm`, and `.mkv`. Timestamps in case files are seconds from the start of the decoded clip.

## Cloud-stored Videos

GlassKit supports AWS S3, Cloudflare R2, and other S3-compatible object stores. This keeps large recordings out of your app repository and makes them easier to share with a team. Eval commands download videos when needed and reuse cached copies on later runs.

Define a named store in `<eval-dir>/config.yaml`. For a private Cloudflare R2 store, configure credentials through environment variables:

```yaml
video_stores:
  team-videos:
    type: s3
    bucket: team-eval-videos
    endpoint_url: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
    region: auto
    access_key_id_env: EVAL_STORAGE_ACCESS_KEY_ID
    secret_access_key_env: EVAL_STORAGE_SECRET_ACCESS_KEY
```

Keep the credential values in an ignored `.env` file or your team's secret manager:

```dotenv
EVAL_STORAGE_ACCESS_KEY_ID=...
EVAL_STORAGE_SECRET_ACCESS_KEY=...
```

Upload a recording from the directory containing your eval setup:

```sh
uv run --env-file .env glasskit eval video-store upload recordings/task-01.mp4 --store team-videos
```

The command prints a `video:` block to copy into the case file:

```yaml
video:
  store: team-videos
  key: abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789.mp4
  sha256: abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789
targets:
  step_1:
    samples:
    - at: 0
      expect: false
```

The `store`, `key`, and `sha256` values identify the uploaded video. Copy them as printed rather than writing them by hand. Ordinary `run`, `seed`, `validate`, `export-frames`, and `review` commands download cloud videos automatically.

For AWS S3, omit `endpoint_url` and use the bucket's AWS region. You can also omit the custom credential variable names to use the standard AWS credential configuration:

```yaml
video_stores:
  team-evals:
    type: s3
    bucket: team-eval-videos
    region: us-east-1
```

`access_key_id_env` and `secret_access_key_env` must be set together, and temporary credentials can add `session_token_env`. Only `bucket` is required: `type` defaults to `s3` and `region` defaults to `us-east-1`.

Omit `--key` when uploading to let GlassKit use `<sha256><extension>` as the object key. Uploading is idempotent: when the destination object already exists with a matching size and SHA-256, the command reports that and prints the same `video:` block; any other existing object at the key is refused rather than overwritten. Use `pull` when you want to download selected videos ahead of time:

```sh
uv run --env-file .env glasskit eval video-store pull
uv run --env-file .env glasskit eval video-store pull --case task-01
```

`list-samples` validates cloud references without downloading videos. Downloads are stored in a per-user cache outside the eval directory — `~/Library/Caches/glasskit/eval/videos` on macOS, `$XDG_CACHE_HOME/glasskit/eval/videos` on Linux when `XDG_CACHE_HOME` is set (otherwise `~/.cache/glasskit/eval/videos`), and `%LOCALAPPDATA%\GlassKit\Cache\eval\videos` on Windows — and shared by all of that user's eval directories. Set `GLASSKIT_EVAL_CACHE_DIR` to override the location. To clear downloaded videos, run `glasskit eval video-store prune-cache --all`; they will be downloaded again when needed.

### Public Downloads

For a public repository, you may want anyone to run the eval without storage credentials while allowing only maintainers to upload. Expose the bucket through a public HTTP URL and add it to the store:

```yaml
video_stores:
  public-evals:
    type: s3
    bucket: public-eval-videos
    endpoint_url: https://<S3_API_ENDPOINT>
    region: <REGION>
    public_base_url: https://<PUBLIC_BUCKET_HOST>
    access_key_id_env: EVAL_STORAGE_ACCESS_KEY_ID
    secret_access_key_env: EVAL_STORAGE_SECRET_ACCESS_KEY
```

Downloads then use `public_base_url` without credentials. Uploads still require the configured credentials.

## Case File Reference

Here is a representative case file:

```yaml
video: task-01.mp4
description: Step 1 should be detected after the bracket is seated.
sampling:
  every_s: 0.5
targets:
  step_1:
    label: Step 1
    config:
      prompt_id: workflow.step_1
      reference_image: assets/step_1.png
    samples:
    - range: [0.0, 6.8]
      expect: false
      comment: The bracket is not seated yet.
    - range: [7.4, 11.8]
      every_s: 0.25
      field: result.matches
      expect: true
    - at: 11.9
      expect: true
      ignore: Difficult frame with known flaky observations.
  step_2:
    label: Step 2
    samples:
    - at: [4.0, 6.0] # Two discrete samples, not a range.
      expect: false
thresholds:
  min_pass_rate: 0.9
  max_failures: 2
  per_target:
    step_1:
      min_pass_rate: 0.95
```

Case fields:

| Field | Required | Description |
| --- | ---: | --- |
| `video` | Yes | Local path resolved relative to the case file, or an object with required `store`, `key`, and `sha256` fields for a cloud video. |
| `description` | No | Human-readable case note. |
| `sampling.every_s` | No | Default range sampling interval in seconds. Defaults to `0.5`; must be greater than `0`. |
| `sample_defaults` | No | Case-wide defaults for sample `field` and `compare`. Target defaults override these values, and sample blocks override both scopes. |
| `workflow.targets` | No | Optional advanced target metadata list for imported or generated workflow definitions. |
| `targets` | Yes | Mapping of target id to target definition. Must contain at least one target. |
| `thresholds` | No | Case-level gates: `min_pass_rate`, `max_failures`, and `per_target.<target>.min_pass_rate`. Omitted keys create no gate for that key. |

Target fields:

| Field | Required | Description |
| --- | ---: | --- |
| `label` | No | Display name shown in reports. |
| `config` | No | Adapter-specific metadata for the target. Use this as the default place for prompt IDs, rubric IDs, reference assets, confidence thresholds, or other target-specific settings. Defaults to an empty object. Values override matching keys from `workflow.targets`. |
| `sample_defaults` | No | Target-wide defaults for sample `field` and `compare`. These override case defaults. |
| `samples` | Yes | List of sample blocks. Empty lists are invalid unless `--allow-empty` is used. |

Most evals should put adapter metadata directly under `targets.<id>.config`. `workflow.targets` is useful when an eval is generated from or synchronized with an app workflow manifest and workflow-owned metadata should stay separate from eval-owned samples, expectations, and per-case overrides. Each workflow target needs an `id`; `label` and extra metadata keys are allowed. Entries are matched by `id`, and their metadata keys other than `id` and `label` are merged into the adapter target config before `targets.<id>.config` is applied. A workflow `label` is used as the target's display label when the target does not define one, and entries whose `id` matches no target are ignored:

```yaml
workflow:
  targets:
  - id: step_1
    app_step_id: 123
    prompt_id: workflow.step_1
targets:
  step_1:
    config:
      confidence_threshold: 0.85
    samples:
    - at: 8.0
      expect: true
```

Sample block fields:

| Field | Required | Description |
| --- | ---: | --- |
| `range` | Conditionally | Two-element `[start, end]` interval in seconds. Exactly one of `range` or `at` is required. The interval is half-open. |
| `at` | Conditionally | One timestamp or a list of timestamps in seconds. Exactly one of `range` or `at` is required. Lists are sorted during expansion. |
| `expect` | For non-ignored runnable samples | JSON-like expected value: `null`, boolean, finite number, string, array, or object with string keys. Omit it to create a draft sample for `seed`; explicit `null` is a labeled expectation. Ignored samples may omit it without becoming drafts. |
| `every_s` | No | Per-block range sampling interval. Defaults to `sampling.every_s` for the case, which defaults to `0.5`. |
| `field` | No | Dot-separated path to extract from the adapter observation before comparison. An omitted value inherits target or case `sample_defaults`; without a default, the whole observation is compared. Explicit `null` clears an inherited field. |
| `compare` | No | Comparison config with `mode` and optional `tolerance`. An omitted value inherits target or case `sample_defaults`; without a default, mode is inferred from `expect` and numeric tolerance is `0.0`. Explicit `null` clears an inherited comparison. |
| `comment` | No | Human-readable note retained with the expectation. It does not affect adapter calls or comparison. |
| `ignore` | No | Nonempty reason for ignoring this block. Ignored samples do not need `expect`; they are reported but are not decoded, sent to the adapter, seeded, or included in pass rates, failure counts, or quality gates. |

Sample times must be finite and nonnegative. Ranges must have `end` greater than `start`. Overlapping or duplicate samples for the same target are invalid; overlap is checked on the declared `at` times and `range` intervals, so two blocks with overlapping ranges are rejected even when their expanded samples would not collide. Expansion is capped at 10,000 samples across all targets in one case; pathological ranges are rejected before their samples are materialized. Unknown keys anywhere in a case file are validation errors, so a misspelled field name fails fast instead of being silently ignored; only `workflow.targets` entries accept extra metadata keys.

Use `ignore` for a known exceptional sample that should remain documented without affecting a run. An ignored `at` list or `range` ignores every expanded sample in that block; use a single `at` timestamp when only one sample is exceptional.

Sample settings use the precedence `sample block > target sample_defaults > case sample_defaults > built-in behavior`. `compare` is inherited or replaced as one complete value rather than merged key by key, so an override never retains an unrelated tolerance from a broader scope. Only `field` and `compare` can be defaulted; expectations, locations, comments, and ignore reasons remain explicit sample-block properties.

For example, these defaults apply a structured result envelope and subset comparison to every target in the case, while the `confidence` target replaces both settings:

```yaml
sample_defaults:
  field: result
  compare:
    mode: json_subset
targets:
  object_detection:
    samples:
    - range: [180.0, 182.0]
      expect:
        object: coffee_mug
        color: red
  confidence:
    sample_defaults:
      field: result.confidence
      compare:
        mode: numeric
        tolerance: 0.05
    samples:
    - at: 182.0
      expect: 0.9
```

## Comparison Reference

The adapter observation and the sample `expect` value must both be JSON-like. For simple checks, return only the value you want compared and omit `field`. Use `field` when the adapter naturally returns a structured result but only one nested value should determine correctness. For example, an adapter can return its result alongside diagnostic metadata; selecting the result with `field` makes it the seeded and compared value while preserving the complete adapter response in machine-readable reports and saved failure artifacts.

Field paths are dot-separated. Mapping keys are matched by name, and list indexes can be addressed with nonnegative numeric path parts such as `detections.0.label`. Missing fields fail the sample with an `adapter observation is missing configured field: ...` reason.

Supported comparison modes:

| Mode | Description |
| --- | --- |
| `exact` | Observed value must equal `expect`. Booleans only match booleans. |
| `numeric` | Observed and expected values must be numbers. `tolerance` defaults to `0.0`. |
| `json_subset` | Every expected key and value must be present in the observed object. For arrays, expected items are matched one-for-one against observed items, so duplicate expected items require duplicate observed matches. |
| `set_equals` | Observed and expected arrays are compared as unordered JSON sets. |
| `set_contains_any` | At least one expected array item must be present in the observed array. |
| `set_contains_all` | Every expected array item must be present in the observed array. |

Default comparison modes are inferred from `expect`: booleans, strings, and `null` use `exact`; numbers use `numeric`; arrays and objects use `exact`.

Example:

```yaml
targets:
  detector:
    samples:
    - at: 2.0
      field: result.matches
      expect: true
    - at: 3.0
      field: result.confidence
      expect: 0.8
      compare:
        mode: numeric
        tolerance: 0.05
    - at: 4.0
      field: detected_classes
      expect:
      - bracket
      - fastener
      compare:
        mode: set_contains_all
```

## Adapter Reference

GlassKit Eval supports in-process Python adapters and language-neutral command adapters. Both expose the same individual or batch evaluation behavior to the runner. Use a Python adapter when the app logic is importable by Python, or `--adapter-command` when the adapter should run in its own process, such as a JavaScript or TypeScript backend.

### Python Adapters

By default, `glasskit eval seed` and `glasskit eval run` load `<eval-dir>/adapter.py:create_evaluator`. With the default eval directory, that is `eval/adapter.py:create_evaluator`.

Use `--adapter <module-or-file>:<callable>` to choose another adapter target. The module side can be an import path such as `my_app.eval_adapter` or a file path such as `eval/adapter.py`. The callable side can name a function, class, or nested attribute such as `create_evaluator` or `EvalAdapters.step_checker`.

Keep the adapter thin by reusing as much of the app's runtime logic as practical and adding only the wrappers needed for recorded-video evaluation.

The recommended adapter shape is a factory that accepts one config argument and returns an evaluator object:

```python
from __future__ import annotations

import os
from typing import Any


def create_evaluator(config: Any) -> "Evaluator":
    settings = dict(config.config)
    return Evaluator(
        api_key=os.environ["MODEL_API_KEY"],
        model=settings.get("model", "default-model"),
        verbose=bool(config.verbose),
    )


class Evaluator:
    def __init__(self, *, api_key: str, model: str, verbose: bool) -> None:
        self._api_key = api_key
        self._model = model
        self._verbose = verbose

    async def evaluate(self, sample: Any, target: Any) -> bool:
        return await call_model_backend(
            api_key=self._api_key,
            model=self._model,
            image=sample.image,
            prompt_id=target.config.get("prompt_id", target.id),
            timestamp_s=sample.timestamp_s,
        )

    async def close(self) -> None:
        await close_model_client()
```

Adapter factories may be synchronous or asynchronous. No-argument factories are supported, but they do not receive the factory config object. If the factory needs `--adapter-config`, `--artifacts-dir`, `--verbose`, or the eval directory, define it with one required argument.

### Individual and Batch Evaluation

An evaluator chooses one of two execution strategies by implementing `evaluate` or `evaluate_many`. Both methods may be synchronous or asynchronous.

| Strategy | Adapter method | GlassKit Eval execution | Use when |
| --- | --- | --- | --- |
| Individual | `evaluate(sample, target)` | Calls the method once per sample, with at most `--concurrency` calls in flight for the current target. | Each sample maps to an independent request or local operation. This is the recommended default for ordinary model APIs. |
| Batch | `evaluate_many(samples, target)` | Calls the method once per target with that target's selected decoded samples. GlassKit Eval does not schedule the samples inside the batch. | The provider has a real multi-input endpoint, or the adapter can materially reuse work across the target's samples. |

Implement at least one strategy. If an evaluator implements both methods, `evaluate_many` takes precedence. Batch evaluation must return exactly one JSON-like observation per input sample in the same order. A batch adapter owns any chunking or internal concurrency it needs; `--concurrency` does not fan out calls inside `evaluate_many`.

Samples with an `ignore` reason are omitted before either strategy runs. They are not decoded and are not present in the `samples` list passed to `evaluate_many`. GlassKit Eval schedules the remaining samples in case-file declaration order and passes batch samples in that order. During `seed` and resumed runs, only samples that still need work are passed, so a batch adapter must not assume it always receives a target's complete sample set.

Prefer `evaluate` when the work consists of independent calls, even if those calls should overlap. GlassKit Eval bounds synchronous and asynchronous calls by `--concurrency` and restores deterministic sample order after calls finish. With `--keep-going`, an individual call failure becomes an error only for that sample.

Use `evaluate_many` only for actual batch behavior. If a batch call fails, GlassKit Eval cannot attribute the failure to one input, so `--keep-going` records an error for every sample in that target batch.

The optional `close()` method is called after the run or adapter validation check and may also be synchronous or asynchronous. With `--repeat`, GlassKit Eval creates fresh evaluator instances sequentially and closes each trial before calling the evaluator factory for the next one.

Simple function adapters are also supported when the first two positional argument names are either `image, target_id` or `sample, target`:

```python
def evaluate_frame(image, target_id):
    return target_id == "step_1"
```

Factory `config` fields:

| Field | Description |
| --- | --- |
| `eval_dir` | Resolved eval directory path. |
| `config` | Mapping loaded from the discovered `adapter.yaml` or an explicit `--adapter-config`, or an empty mapping. |
| `artifacts_dir` | Path from `--artifacts-dir`, or `None`. |
| `verbose` | Boolean from `--verbose`. |

Sample fields passed to the evaluator:

| Field | Description |
| --- | --- |
| `image` | Display-oriented RGB `PIL.Image.Image` for the nearest decoded frame at the requested timestamp. |
| `timestamp_s` | Requested sample timestamp in seconds from the start of the clip, from `at` or the expanded `range`. |
| `frame_index` | Zero-based decoded video frame index chosen for that timestamp. |
| `sample_index` | Case-local sample index. |
| `video_path` | Local video file path as a string. For cloud-stored videos this is the downloaded cache file. |
| `case_name` | Case filename stem. |

Frame sampling is timestamp-based. `sample.timestamp_s` is always the requested eval time, not the actual media timestamp of the selected frame. `sample.image` is the decoded frame whose timestamp is closest to that requested time, with ties choosing the earlier frame. GlassKit applies the source video's display rotation and reflection before handing the frame to an adapter, so its pixels and dimensions match normal video playback. For variable-frame-rate videos, `glasskit eval` uses each frame's media timestamp when available; if a video lacks frame timestamps, it estimates them from the frame index and average frame rate.

`sample.image` is closed when the evaluate call returns. Call `sample.image.copy()` if the adapter needs to keep the frame afterward.

Target fields passed to the evaluator:

| Field | Description |
| --- | --- |
| `id` | Target id from the case file. |
| `index` | Target's zero-based order in the case file. |
| `label` | Optional target label. |
| `config` | Adapter-specific target metadata from `targets.<id>.config`, plus matching metadata keys other than `id` and `label` from `workflow.targets`; `targets.<id>.config` wins on conflicts. |

Adapter return values must be JSON-like: `None`, boolean, finite number, string, array, or object with string keys.

### Command Adapters

Use `--adapter-command` when the app is easier to call from its own runtime, such as a JavaScript or TypeScript backend:

```sh
glasskit eval run --adapter-command "node eval/adapter.js"
```

GlassKit Eval parses the command into an argument list, then starts it directly without a shell. Pipes, redirects, variable expansion, and command substitution are therefore unavailable. The command inherits the current working directory and environment, so it can import the app normally and read the same secrets and configuration.

Start from the complete JavaScript file below. Its editable application section passes a factory to `runGlassKitAdapter`; the protocol function handles communication with GlassKit Eval. Stdout belongs to that function, so write application and dependency logs to stderr with `console.error()`. GlassKit Eval mirrors adapter stderr to its own stderr and quotes the most recent output in error messages.

The factory runs once per eval trial and receives this context:

| Field | Description |
| --- | --- |
| `evalDir` | Absolute eval directory path. |
| `config` | Object loaded from the discovered `adapter.yaml` or an explicit `--adapter-config`, or an empty object. |
| `artifactsDir` | Absolute path from `--artifacts-dir`, or `null`. |
| `verbose` | Boolean from `--verbose`. |

Return an object with at least one evaluation method:

| Method | Purpose |
| --- | --- |
| `evaluate({sample, target, signal})` | Evaluate one sample. Use this for ordinary independent backend calls. |
| `evaluateMany({samples, target, signal})` | Evaluate one target's samples as a real batch and return one observation per sample in the same order. If both evaluation methods exist, this one takes precedence. |
| `close()` | Optional cleanup for app clients and other resources. |

The individual and batch scheduling behavior is the same as described above. Multiple `evaluate` calls can be active at once according to `--concurrency`, so shared app clients and mutable state must support that. Pass the provided `AbortSignal` through to backend calls when possible. Throw an error to report a failed call; otherwise return a JSON-compatible observation.

Command-adapter samples contain the same information as Python samples, using lower camel case for field names:

| Field | Description |
| --- | --- |
| `image` | `{mimeType, bytes, width, height}`, where `bytes` is a Node.js `Buffer` containing the display-oriented lossless PNG. On the wire this field arrives as `dataBase64`, a base64 string that the protocol function below decodes into `bytes` before calling the app. |
| `timestampS` | Requested sample timestamp in seconds. |
| `frameIndex` | Zero-based decoded video frame index selected for that timestamp. |
| `sampleIndex` | Case-local sample index. |
| `videoPath` | Local video file path as a string; for cloud-stored videos, the downloaded cache file. Do not decode it again; `image` is already the selected frame. |
| `caseName` | Case filename stem. |

Targets use the `id`, `index`, `label`, and `config` fields described above. GlassKit-owned fields use lower camel case; keys inside the user-provided factory and target `config` objects are preserved unchanged. `glasskit eval validate --adapter-command ...` constructs and closes the adapter without evaluating samples.

After answering the final `close` request, the adapter process must exit promptly with status `0`; GlassKit Eval waits about five seconds before terminating the process and its children. Protocol messages are limited to 256 MiB in each direction, which bounds how many PNG frames one `evaluateMany` batch can carry.

In this `eval/adapter.js`, replace `createAppClient` and its methods with thin calls into the app, then keep the marked protocol function unchanged. Application clients stay in the factory's closure, and supported methods are detected automatically. The example uses an ECMAScript module; use `.mjs` or set `"type": "module"` in the app's `package.json` when needed.

For adapters in other languages, use the JavaScript implementation below as an executable protocol reference.

```js
// Application code: replace these calls with the app's imports and logic.
await runGlassKitAdapter(async (context) => {
  const app = await createAppClient(context.config);

  return {
    async evaluate({ sample, target, signal }) {
      return await app.evaluateFrame({
        image: sample.image.bytes,
        mimeType: sample.image.mimeType,
        promptId: target.config.promptId ?? target.id,
        timestampS: sample.timestampS,
        signal,
      });
    },

    // If the app has a real multi-input API, implement
    // evaluateMany({ samples, target, signal }) instead.

    async close() {
      await app.close();
    },
  };
});

// ---- GlassKit Eval protocol ----
async function runGlassKitAdapter(createEvaluator) {
  const { createInterface } = await import("node:readline");
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const active = new Map();
  let evaluator;
  let closing = false;
  let outputTail = Promise.resolve();

  function send(message) {
    const line = `${JSON.stringify(message)}\n`;
    outputTail = outputTail.then(
      () =>
        new Promise((resolve, reject) => {
          process.stdout.write(line, "utf8", (error) => {
            if (error) reject(error);
            else resolve();
          });
        }),
    );
    return outputTail;
  }

  function errorPayload(error) {
    return {
      message: error instanceof Error ? error.message : String(error),
      ...(error instanceof Error && error.stack ? { stack: error.stack } : {}),
    };
  }

  function sampleForApp(sample) {
    const { dataBase64, ...image } = sample.image;
    return {
      ...sample,
      image: { ...image, bytes: Buffer.from(dataBase64, "base64") },
    };
  }

  async function respond(request, operation) {
    try {
      await send({ id: request.id, result: await operation() });
    } catch (error) {
      await send({ id: request.id, error: errorPayload(error) });
    }
  }

  async function initialize(request) {
    await respond(request, async () => {
      if (request.params.protocolVersion !== 1) {
        throw new Error(
          `unsupported protocol version: ${request.params.protocolVersion}`,
        );
      }
      evaluator = await createEvaluator(request.params.config);
      const capabilities = {
        evaluate: typeof evaluator?.evaluate === "function",
        evaluateMany: typeof evaluator?.evaluateMany === "function",
      };
      if (!capabilities.evaluate && !capabilities.evaluateMany) {
        throw new Error("adapter must implement evaluate or evaluateMany");
      }
      return { protocolVersion: 1, capabilities };
    });
  }

  function startEvaluation(request) {
    const controller = new AbortController();
    const operation = async () => {
      if (!evaluator) throw new Error("adapter is not initialized");
      if (request.method === "evaluate") {
        return await evaluator.evaluate({
          sample: sampleForApp(request.params.sample),
          target: request.params.target,
          signal: controller.signal,
        });
      }
      return await evaluator.evaluateMany({
        samples: request.params.samples.map(sampleForApp),
        target: request.params.target,
        signal: controller.signal,
      });
    };
    const promise = respond(request, operation);
    active.set(request.id, { controller, promise });
    promise.then(
      () => active.delete(request.id),
      (error) => {
        active.delete(request.id);
        console.error("Could not write GlassKit Eval adapter response:", error);
        process.exitCode = 1;
      },
    );
  }

  async function closeEvaluator() {
    const currentEvaluator = evaluator;
    evaluator = undefined;
    if (typeof currentEvaluator?.close === "function") {
      await Promise.resolve(currentEvaluator.close());
    }
  }

  async function close(request) {
    closing = true;
    await Promise.allSettled([...active.values()].map(({ promise }) => promise));
    await respond(request, async () => {
      await closeEvaluator();
      return null;
    });
    lines.close();
    process.stdin.pause();
  }

  for await (const line of lines) {
    let request;
    try {
      request = JSON.parse(line);
    } catch (error) {
      console.error("Invalid GlassKit Eval protocol request:", error);
      process.exitCode = 1;
      break;
    }
    if (request.method === "cancel") {
      active.get(request.params.id)?.controller.abort();
    } else if (request.method === "initialize") {
      await initialize(request);
    } else if (
      request.method === "evaluate" ||
      request.method === "evaluateMany"
    ) {
      startEvaluation(request);
    } else if (request.method === "close") {
      await close(request);
    } else {
      await send({
        id: request.id,
        error: { message: `unknown method: ${request.method}` },
      });
    }
  }

  if (!closing) {
    for (const { controller } of active.values()) controller.abort();
    await Promise.allSettled([...active.values()].map(({ promise }) => promise));
    await closeEvaluator();
  }
  await outputTail;
}
```

## Command Reference

Every command supports `--help`.

### `glasskit`

Purpose: top-level command group.

```sh
glasskit --help
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--version` | None | Show the installed GlassKit version and exit. |
| `--install-completion` | None | Install shell completion for the current shell. |
| `--show-completion` | None | Print shell completion setup text. |
| `--help` | None | Show help and exit. |

Commands:

| Command | Description |
| --- | --- |
| `eval` | Recorded-video eval tools. |

### `glasskit eval`

Purpose: command group for recorded-video evals.

```sh
glasskit eval --help
```

Commands:

| Command | Description |
| --- | --- |
| `run` | Decode selected frames, call the adapter, compare observations, apply gates, and report results. |
| `seed` | Run a labeling adapter and write proposed expectations into selected draft samples. |
| `review` | Open the local browser UI for inspecting and correcting timed expectations. |
| `validate` | Check eval structure, videos, sample times, and optional adapter construction without running samples. |
| `list-samples` | Print the expanded sample schedule for inspection or debugging. |
| `export-frames` | Export the eval-decoded image at one or more case timestamps. |
| `video-store` | Pull, upload, and prune cached videos backed by cloud object storage. |

### `glasskit eval video-store`

Purpose: manage videos backed by an S3-compatible cloud object store. Ordinary eval commands fetch cloud videos automatically.

```sh
glasskit eval video-store --help
```

Commands:

| Command | Description |
| --- | --- |
| `pull` | Download all selected cloud videos. Accepts `--eval-dir` and optional `--case`. |
| `upload SOURCE --store NAME` | Upload a local video through the named store's authenticated S3 API and print a case-file `video:` block. Accepts optional `--key` and `--eval-dir`. |
| `prune-cache` | Remove abandoned partial downloads older than one hour. Add `--all` to remove downloaded videos too. Operates on the current user's cache across eval directories. |

### `glasskit eval seed`

Purpose: fill missing expectations in selected draft cases using an adapter, or explicitly replace existing expectations in the selected scope.

```sh
glasskit eval seed --case task-01 --target step_1
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--adapter TEXT` | `<eval-dir>/adapter.py:create_evaluator` | Labeling adapter target in `<module-or-file>:<callable>` form. It uses the same contract as the run adapter. |
| `--adapter-command TEXT` | None | Process labeling adapter command. Mutually exclusive with `--adapter`; when set, the Python adapter default is not loaded. |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--case TEXT` | All cases | Only seed one case by filename or stem. |
| `--target TEXT` | All targets | Only seed this target id from the selected cases. Repeat the option to seed multiple targets. Every requested target must exist in the selected case scope. May be used with or without `--case`. |
| `--adapter-config PATH` | `<eval-dir>/adapter.yaml` when present | YAML or JSON object passed to the selected adapter in its `config` field. |
| `--concurrency INTEGER` | `1` | Maximum concurrent per-sample `evaluate` calls within a target. Must be greater than zero. Ignored for adapters using `evaluate_many`, which control their own batch execution. |
| `--replace` | `false` | Evaluate and replace existing expectations in the selected scope as well as filling missing ones. |
| `--keep-going` | `false` | Checkpoint per-sample adapter or field-extraction errors and continue evaluating. The case YAML remains unchanged unless every selected expectation succeeds. |
| `--resume PATH` | None | Resume an incomplete seed checkpoint by its printed path or checkpoint id. The checkpoint restores the original adapter, filters, config, concurrency, and seed options, so it cannot be combined with overrides; only `--eval-dir` may be repeated, to locate a checkpoint given by id. |
| `--verbose` | `false` | Print every proposed expectation and set the factory config object's `verbose` field. |

When `field` is present on a sample block, `seed` extracts that path from the adapter's observation and writes the extracted value as `expect`; otherwise it writes the complete observation. Existing expectations outside the selected filters, and inside the filters without `--replace`, are preserved. Ignored samples are never seeded, even with `--replace`, and may omit `expect`. Other missing expectations outside the selected filters may remain draft; `run`, `validate`, and `list-samples` reject draft samples only when they fall inside those commands' selected scope.

Each successful adapter result is durably checkpointed before the command advances. If seeding is interrupted or an adapter call fails after at least one result succeeds, the case file is left unchanged and the error output prints an exact `glasskit eval seed --resume ...` command. Setup failures and attempts with no successful results do not print a resume command, because rerunning the original command repeats no completed adapter work. Resume evaluates only checkpointed errors and unfinished samples, including when the original operation used `--replace`. Once all selected expectations are available, `seed` validates and atomically replaces the complete case YAML. Resume does not automatically retry calls; each invocation makes at most one new attempt for each selected pending sample. Resume also checks its inputs for changes; if it detects one, resuming stops with a `checkpoint inputs changed` error and the operation must be restarted.

Exit behavior: exits `0` after seeding or when the selected scope has nothing to seed, `1` when `--keep-going` attempted the selected scope but one or more expectations remain incomplete, `2` for invalid input, an adapter failure that aborted evaluation, or a case file that cannot be updated, and `130` when interrupted with `Ctrl+C`. Interrupted and incomplete operations retain checkpoints only when they contain successful adapter results.

### `glasskit eval review`

Purpose: launch the local eval review UI without loading or running an adapter.

```sh
glasskit eval review --eval-dir eval --case task-01 --target step_1 --time 7.4
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--case TEXT` | First case | Initially open one case by filename or stem. It does not hide other cases. |
| `--target TEXT` | First target | Initially focus one target from `--case`. Requires `--case` and does not hide other targets. |
| `--time FLOAT` | None | Initially seek to a finite, nonnegative time in the selected case. Requires `--case`. |
| `--port INTEGER` | `0` | Loopback port. `0` chooses an available port. |
| `--no-open` | `false` | Print the URL without opening the default browser. |

Because edits are saved directly to the case file, commit or copy case files before editing if you want an easy way to review or undo the changes. Saving may reformat the YAML and remove ordinary YAML comments; values stored in sample `comment` and `ignore` fields are preserved.

Exit behavior: exits `0` after a normal `Ctrl+C` shutdown and `2` for an invalid eval path or selector, invalid option combination, or failure to load or start the review UI. Failure to open the browser is nonfatal because the printed URL remains usable.

### `glasskit eval export-frames`

Purpose: export the exact display-oriented frames GlassKit would pass to an adapter at arbitrary points in one case.

```sh
glasskit eval export-frames --case task-01 --at 7.5 --at 8.0
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--case TEXT` | Required | Case filename or stem containing the source video. |
| `--at FLOAT` | Required | Nonnegative frame time in seconds. Repeat to export multiple times in one video decode. Duplicate times are exported once. |
| `--output-dir PATH` | `<eval-dir>/runs/frames/<case>/` | Directory for exported PNGs. |

Each image is named `at-<timestamp>s.png`. A frame with the same destination name is replaced, and the command prints only the absolute path of each written image, in requested order. Timestamps do not need to be declared samples, and draft or ignored samples do not prevent export.

Frame selection is identical to eval execution: GlassKit chooses the nearest decoded frame, chooses the earlier frame on a tie, and applies the video's display rotation and reflection before writing a lossless RGB PNG. A time beyond the source video duration is rejected.

Exit behavior: exits `0` after exporting every requested frame and `2` for an invalid eval path, case, timestamp, video, or destination.

### `glasskit eval run`

Purpose: execute selected eval samples and apply quality gates, with optional repetition for measuring stability.

```sh
glasskit eval run --case task-01 --output-json eval/runs/results.json
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--adapter TEXT` | `<eval-dir>/adapter.py:create_evaluator` | Adapter target in `<module-or-file>:<callable>` form. |
| `--adapter-command TEXT` | None | NDJSON process adapter command. Mutually exclusive with `--adapter`; when set, the Python adapter default is not loaded. |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--case TEXT` | All cases | Only run one case by filename or stem. Do not include path separators. |
| `--target TEXT` | All targets | Only run this target id from the selected cases. Repeat the option to run multiple targets. Every requested target must exist in the selected case scope. May be used with or without `--case`. |
| `--at FLOAT` | None | Only run samples scheduled at this time in seconds. Repeat to select multiple times. Requires `--case` and cannot be combined with `--from` or `--until`. |
| `--from FLOAT` | None | Only run samples scheduled at or after this time in seconds. Requires `--case`. |
| `--until FLOAT` | None | Only run samples scheduled before this time in seconds. Requires `--case`. |
| `--adapter-config PATH` | `<eval-dir>/adapter.yaml` when present | YAML or JSON object passed to the selected adapter in its `config` field. |
| `--concurrency INTEGER` | `1` | Maximum concurrent per-sample `evaluate` calls within a target. Must be greater than zero. Ignored for adapters using `evaluate_many`, which control their own batch execution. |
| `--repeat INTEGER` | `1` | Number of complete executions. Values above `1` run sequential trials with a fresh evaluator for each one. |
| `--min-pass-rate FLOAT` | None | Pass-rate gate from `0.0` to `1.0`. Overrides eval-level `thresholds.min_pass_rate` and suppresses case-level gates when set. |
| `--min-target-pass-rate FLOAT` | None | Uniform per-target pass-rate gate for targets present in the selected results. Replaces eval-level `thresholds.per_target` gates. |
| `--max-failures INTEGER` | None | Maximum failed comparisons. Overrides eval-level `thresholds.max_failures` and suppresses case-level gates when set. |
| `--max-flaky-samples INTEGER` | None | Cross-trial maximum number of samples whose status varies. Must be nonnegative and requires `--repeat` of at least `2`. |
| `--keep-going` | `false` | Record adapter evaluation or comparison errors as sample results and continue. |
| `--resume PATH` | None | Resume an incomplete run checkpoint by its printed path or checkpoint id. The checkpoint restores the original adapter and run options, so it cannot be combined with overrides; only `--eval-dir` may be repeated, to locate a checkpoint given by id. |
| `--verbose` | `false` | Print every sample result and set the factory config object's `verbose` field. |
| `--output-json PATH` | None | Write a machine-readable JSON report. |
| `--artifacts-dir PATH` | None | Base directory for generated artifacts. Failure artifacts are written below its `failures/` subdirectory; when omitted, the base is `<eval-dir>/runs/`. |
| `--save-failures` | `false` | Save failed or errored sample frames and per-result JSON. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

`--at`, `--from`, and `--until` select samples already scheduled in the case; they do not create samples at arbitrary video times. Repeat `--at` to select multiple timestamps. Each requested timestamp must be present among the samples chosen by `--case` and `--target`. `--from` is inclusive, `--until` is exclusive, either range bound may be used alone, and when both are given `--until` must be greater than `--from`. All three options require `--case`, and `--at` cannot be combined with either range bound. Only selected samples are sent to the adapter, and quality gates apply to the selected results.

Every completed sample result is durably checkpointed. If a fail-fast run is interrupted after at least one adapter evaluation completes, its error output prints an exact `glasskit eval run --resume ...` command. With `--keep-going`, the normal report still contains adapter errors and fails the automatic `adapter_errors` gate, while its summary prints a resume command only when the checkpoint contains completed adapter work. Setup failures and attempts where every adapter call fails do not print a resume command. Resume reuses successful evaluations, ordinary comparison failures, ignored samples, and comparison-error results; it evaluates only adapter errors and unfinished samples. No adapter call is retried automatically. A resumed run writes a JSON report or failure artifacts only when the original invocation requested them. Resume also checks its inputs for changes; if it detects one, resuming stops with a `checkpoint inputs changed` error.

Exit behavior: exits `0` when every configured gate passes, `1` when the eval completed but one or more gates failed, `2` when setup or runtime errors abort the run, and `130` when interrupted with `Ctrl+C`.

### `glasskit eval validate`

Purpose: check an eval directory without evaluating sample observations. A normal `run` performs the same eval structure, video, and sample-time checks before calling the adapter, so a separate validation step is not required. Use `validate` when you want an inexpensive standalone check, such as in a configuration-only CI job or before using a slow or paid adapter.

```sh
glasskit eval validate --adapter eval/adapter.py:create_evaluator
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--adapter TEXT` | None | Optional Python adapter target to verify. |
| `--adapter-command TEXT` | None | Optional process adapter command to verify. Mutually exclusive with `--adapter`. |
| `--case TEXT` | All cases | Only validate one case by filename or stem. |
| `--target TEXT` | All targets | Only validate this target id from the selected cases. Repeat the option to validate multiple targets. Every requested target must exist in the selected case scope. May be used with or without `--case`. |
| `--adapter-config PATH` | `<eval-dir>/adapter.yaml` when present | YAML or JSON object passed to the selected adapter during validation. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

When `--adapter` or `--adapter-command` is provided, validation also constructs and closes that adapter. It does not evaluate a sample or verify the adapter's observations. Without either option, validation checks only the eval directory and selected cases.

Exit behavior: exits `0` when validation passes, `1` when validation fails, and `2` for CLI usage errors such as combining `--adapter` with `--adapter-command`.

### `glasskit eval list-samples`

Purpose: inspect the expanded sample schedule when debugging ranges, timestamp filters, fields, or comparison modes.

```sh
glasskit eval list-samples --case task-01
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--case TEXT` | All cases | Only list one case by filename or stem. |
| `--target TEXT` | All targets | Only list this target id from the selected cases. Repeat the option to list multiple targets. Every requested target must exist in the selected case scope. May be used with or without `--case`. |
| `--at FLOAT` | None | Only list samples scheduled at this time in seconds. Repeat to select multiple times. Requires `--case` and cannot be combined with `--from` or `--until`. |
| `--from FLOAT` | None | Only list samples scheduled at or after this time in seconds. Requires `--case`. |
| `--until FLOAT` | None | Only list samples scheduled before this time in seconds. Requires `--case` and must be greater than `--from` when both are set. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

The table includes each sample's case, target, timestamp, expectation, comparison mode, field, and source. Range blocks are half-open: for example, `range: [1.0, 2.0]` with `every_s: 0.5` produces samples at `1.0` and `1.5`, not `2.0`.

Exit behavior: exits `0` when the samples can be listed and `2` when the eval directory cannot be loaded.

## Configuration

`glasskit eval` has no global config file. Eval configuration lives in the eval config file and case files within the eval directory.

Default values at a glance:

| Area | Default When Omitted |
| --- | --- |
| Eval directory | `eval` from the command's working directory. |
| `seed` adapter | Python target `<eval-dir>/adapter.py:create_evaluator`; replaced when `--adapter-command` is set. |
| `run` adapter | Python target `<eval-dir>/adapter.py:create_evaluator`; replaced when `--adapter-command` is set. |
| Individual evaluation concurrency | `1`. Increase with `seed --concurrency` or `run --concurrency`. |
| `<eval-dir>/adapter.yaml` | Optional. Missing file means the adapter receives an empty config object. |
| `<eval-dir>/config.yaml` | Optional. Missing file means no eval-level thresholds or cloud video stores. |
| Case `sampling.every_s` | `0.5` seconds. |
| Sample block `every_s` | Inherits the case `sampling.every_s`. |
| Sample `field` | Inherits target or case `sample_defaults.field`; otherwise compares the whole adapter observation. |
| Sample `compare.mode` | Inherits target or case `sample_defaults.compare`; otherwise inferred from `expect`: non-boolean numbers use `numeric`; booleans, strings, `null`, arrays, and objects use `exact`. |
| Numeric `compare.tolerance` | `0.0`. |
| `targets.<id>.config` | Empty object. Use this as the default place for adapter-specific target metadata. The final adapter target config also includes matching optional metadata (other than `id` and `label`) from `workflow.targets`, with `targets.<id>.config` taking precedence. |
| Threshold keys | Unset. Missing `min_pass_rate`, `max_failures`, and `per_target.<target>.min_pass_rate` keys create no corresponding gate. |
| Adapter config | `<eval-dir>/adapter.yaml` when present, otherwise an empty object; `--adapter-config` overrides discovery. |
| Failure artifacts | Saved only with `--save-failures`; stored below `<eval-dir>/runs/failures/` by default. |
| Frame exports | Written by `export-frames` below `<eval-dir>/runs/frames/<case>/` by default. |
| Checkpoints | Created automatically below `<eval-dir>/runs/checkpoints/`; completed adapter evaluations are fsynced before the command advances, and new error-only checkpoints are discarded. |

`<eval-dir>/config.yaml` supports eval-level thresholds and named `video_stores`. Cloud video store examples and credential behavior are documented in [Cloud-stored Videos](#cloud-stored-videos). Thresholds use this form:

```yaml
thresholds:
  min_pass_rate: 0.9
  max_failures: 5
  per_target:
    step_1:
      min_pass_rate: 0.95
```

All threshold keys default to unset. `glasskit eval` does not treat a missing `min_pass_rate` as `1.0`, `0.0`, or the current pass rate; it skips that pass-rate gate. If every quality threshold is omitted, ordinary failed comparisons still appear in the console report and JSON output, but they do not fail `glasskit eval run`. If another gate is configured, such as `max_failures` or a per-target `min_pass_rate`, ordinary failed comparisons can still fail the run through that gate.

A configured gate with no matching results fails: a `per_target` threshold that names a target absent from the selected results fails at a 0% pass rate rather than passing silently. Per-target gates are skipped only for targets excluded by `--case`, `--target`, or time filters. Pass rates count errored samples in their denominator, so with `--keep-going`, adapter errors lower pass-rate gates in addition to tripping the automatic `adapter_errors` gate.

With `--repeat`, quality gates are calculated separately for every trial, and the overall run fails if any trial fails one. Results are never pooled before applying a quality gate. Flaky samples do not fail the run unless `--max-flaky-samples` is configured. A stable failure satisfies `--max-flaky-samples 0`, so combine stability and quality gates when correctness also matters.

Adapter evaluation errors, non-JSON adapter observations, and unexpected comparison exceptions abort the run with exit code `2` by default. Completed results remain in the printed checkpoint. With `--keep-going`, those sample-level errors are recorded as results with status `error`, and the automatic `adapter_errors` gate makes the completed run fail with exit code `1`. Adapter-error results remain resumable; comparison errors remain completed diagnostic results. Adapter setup, loading, and close errors still abort the command, but any sample results completed before those errors remain checkpointed.

Validation, listing, and running require `expect` on every non-ignored sample in their selected scope. Ignored samples may omit it. If one of those commands reports draft samples, use `glasskit eval seed` to propose their expectations or label them manually. Filters are applied before this check, so a focused command can operate on a ready target while another target in the same case remains draft.

Threshold precedence:

| Source | Applies To | Notes |
| --- | --- | --- |
| `--min-pass-rate` | Selected results | Overrides eval-level `thresholds.min_pass_rate`. When set, case-level gates are not applied. |
| `--max-failures` | Selected results | Overrides eval-level `thresholds.max_failures`. When set, case-level gates are not applied. |
| `--min-target-pass-rate` | Selected targets | Adds the same per-target pass-rate gate for each target present in the selected results and replaces eval-level `thresholds.per_target` gates. Case-level gates still apply unless `--min-pass-rate` or `--max-failures` is set. |
| `--max-flaky-samples` | Repeated run | Counts logical samples with more than one distinct `passed`, `failed`, or `error` status across trials. It does not measure whether stable outcomes are correct. |
| `<eval-dir>/config.yaml` | Selected results | Applies after CLI overrides. Eval-level per-target gates for targets outside a case, target, or time-window filtered run are skipped. |
| `cases/<case>.yaml` `thresholds` | That case | Applies per case unless `--min-pass-rate` or `--max-failures` is set. |

With `--repeat`, the quality-gate precedence above is resolved the same way for each trial, then each gate is evaluated independently against that trial's results.

Other precedence rules:

| Area | Rule |
| --- | --- |
| Range sampling | A sample block's `every_s` overrides case-level `sampling.every_s`. |
| Sample settings | A sample block overrides target `sample_defaults`, which overrides case `sample_defaults`. A declared `compare` replaces the inherited comparison as one value. |
| Target metadata | `targets.<id>.config` is the default place for adapter target metadata and overrides matching keys from optional `workflow.targets` metadata. |
| Adapter config | `<eval-dir>/adapter.yaml`, or the explicit `--adapter-config` override, is independent of the eval config file and case files and is passed only to the selected adapter. |

## Environment Variables

`glasskit eval` reads one CLI-specific environment variable: `GLASSKIT_EVAL_CACHE_DIR` overrides the per-user cache directory for downloaded cloud videos described in [Cloud-stored Videos](#cloud-stored-videos). It does not read user input from stdin.

Adapters may read any environment variables your app needs, such as API keys, backend URLs, or feature flags. Command adapters inherit the GlassKit Eval process environment, and GlassKit Eval reserves their stdin and stdout for the process protocol. Keep secrets out of case files and adapter config files. With `uv`, pass a dotenv file to `uv run`:

```sh
uv run --env-file .env glasskit eval run
```

## Output Formats

Human-readable output is printed as tables to stdout. Pass `--output-json PATH` to retain a machine-readable report after the run. Each sample result records the complete adapter observation in `observed` and the value selected by `field` in `observed_value`, so diagnostic metadata remains available even when only one nested value determines pass/fail. The report's `checkpoint` object records its checkpoint path, whether this invocation resumed it, and how many adapter-error results remain resumable. See the [JSON output reference](https://github.com/RealComputer/GlassKit/blob/main/cli/JSON_OUTPUT.md) for the complete report format, a repeated-run example, and result-structure semantics.

Checkpoints contain adapter configuration and observations and are written with owner-only file permissions. Treat `<eval-dir>/runs/` as sensitive disposable state: keep it out of version control, retain an incomplete checkpoint only while recovery is useful, and remove it manually when it is no longer needed.

`--save-failures` writes artifacts for every failed or errored sample attempt. To prevent repeated executions from overwriting one another, files are grouped under `<eval-dir>/runs/failures/trial-NNN/` by default or `<artifacts-dir>/failures/trial-NNN/` when `--artifacts-dir` is provided. A run without `--repeat` uses `trial-001`. Each saved result includes a JPEG frame and a JSON metadata file named with the case, target, sample index, and timestamp; the metadata also records its one-based trial number.

## Exit Codes

| Code | Meaning | Fix |
| ---: | --- | --- |
| `0` | Command succeeded. For `run`, every configured gate passed. | No action needed. |
| `1` | Validation failed, `seed --keep-going` retained one or more incomplete expectations, or `run` completed but one or more gates failed. | Read the validation issues, incomplete-seed message, or gate tables. Use the printed resume command to retry only adapter errors and unfinished samples. |
| `2` | A CLI usage error, setup error, config error, video error, adapter loading error, or adapter runtime error aborted the command. | Read the error message and validate the eval directory. If a checkpoint is printed, resume it after resolving the error; use `--keep-going` on a new operation when other samples should continue after an error. |
| `130` | `run` or `seed` was interrupted with `Ctrl+C`. | Rerun the command, or use the printed `--resume` command when the checkpoint retained completed adapter work. |

## Support

Questions, bug reports, feature requests, and pull requests are welcome. Use whichever path is easiest:

- Discord: https://discord.gg/v5ayGKhPNP
- GitHub issues and pull requests: https://github.com/RealComputer/GlassKit

For a real app-backed setup, see [this example](https://github.com/RealComputer/GlassKit/tree/main/examples/origami/backend).
