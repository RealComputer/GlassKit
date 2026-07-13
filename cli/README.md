# `glasskit eval`

`glasskit eval` helps you test smart-glasses apps with recorded videos instead of repeated manual runs. Label the moments that matter, connect your app through a small Python adapter, and rerun the same checks locally or in CI.

This is the user manual for the `glasskit` command. For contributor implementation notes, see [AGENTS.md](https://github.com/RealComputer/GlassKit/blob/main/cli/AGENTS.md).

The current command group is `glasskit eval`.

## Why Use This?

Smart-glasses apps often guide a wearer through a task. They watch the live camera feed, track workflow progress, and provide the next instruction or correction when it is useful.

These apps are hard to test manually because every prompt, model, or app logic change can mean repeating the same physical workflow. With `glasskit eval`, you provide a workflow recording, label the expected moments, and replay the same checks whenever the app changes.

Use it when you want a reliable way to test the vision path users depend on and enforce quality gates in CI.

## Installation

The Python package is `glasskit.ai`; it provides the `glasskit` console command. The package requires Python 3.12 or newer and is designed to run with `uv`.

Add it to your app repo's dev dependencies:

```bash
uv add --dev glasskit.ai
uv run glasskit --help
```

Or run it once without adding the dependency:

```bash
uv run --with glasskit.ai glasskit --help
```

The `uv run ...` examples below assume the package has been added to your project. If you use the one-off form, replace `uv run` with `uv run --with glasskit.ai`.

## Quickstart

Start in an app repository checked out next to a `recordings/` directory. This example uses `../recordings/task-01.mp4` from the shell working directory and creates an `eval/` directory in the app repo.

Create the eval directory and write a case file that points at the recording:

```bash
mkdir -p eval/cases
cat > eval/cases/task-01.yaml <<'YAML'
video: ../../../recordings/task-01.mp4
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

```bash
uv run glasskit eval run
```

Expected result: `run` prints case progress, a summary, gates, and a per-target table.

## Core Concepts

An eval directory is the runnable test set. By default, `glasskit eval` uses `eval/` in the current working directory.

A case file is one YAML file under `<eval-dir>/cases/`. The case name is the filename stem.

A video is declared by each case with `video:`. The path is resolved relative to the case file.

A target is one thing the adapter should evaluate, such as `step_1`, `ready_state`, or `detected_objects`.

A sample is one labeled timestamp, or one timestamp expanded from a range. Each sample has an expected JSON-like value.

An adapter is your Python bridge from the CLI to your app's logic. The CLI decodes frames and calls the adapter; the adapter returns observations.

A gate is a quality bar, such as a minimum pass rate or maximum failure count, that turns eval results into a pass/fail signal for CI. Because model-based checks may not always reach 100%, gates let you choose the right bar for your app.

## Common Workflows

### Create a New Eval Case

Goal: create the required directory structure and a case file in `eval/` from an existing recording.

Commands:

```bash
mkdir -p eval/cases
cat > eval/cases/task-02.yaml <<'YAML'
video: ../../../recordings/task-02.mov
description: Replace this note with what task-02 should cover.
sampling:
  every_s: 0.5
targets:
  step_2:
    samples:
    - at: 0.0
      expect: false
YAML
```

Expected result: `eval/cases/task-02.yaml` points to `task-02.mov` in the sibling `recordings/` directory, and the case is ready for timestamp and expectation edits.

Note: If you prefer colocated fixtures, put the recording in `eval/cases/` and set `video:` to the filename, such as `task-02.mov`.

### Validate Before a Run

Goal: catch YAML, video, timestamp, and optional adapter setup problems before calling a paid or slow model backend.

Command:

```bash
uv run glasskit eval validate
```

Expected output:

```text
Validation passed: /absolute/path/to/eval (12 samples)
```

Note: Validation loads the eval directory, probes videos, checks sample timestamps against video duration, and imports, constructs, and closes the adapter when `--adapter` is provided. It does not call `evaluate` or `evaluate_many`.

### Inspect the Expanded Sample Schedule

Goal: confirm that ranges, `at` lists, fields, and compare modes expand as intended.

Command:

```bash
uv run glasskit eval list-samples --case task-01
uv run glasskit eval list-samples --case task-01 --target step_1
```

Expected output: a Rich table with `Case`, `Target`, `Time`, `Expected`, `Mode`, `Field`, and `Source` columns.

Note: Range blocks are half-open intervals. For example, `range: [1.0, 2.0]` with `every_s: 0.5` produces samples at `1.0` and `1.5`, not `2.0`.

### Review and Correct Expectations in the Browser

Goal: make recorded-video expectations faster to verify and correct.

Without the review UI, verifying expectations means juggling a media player and YAML editor while matching timestamps by hand. The review UI puts the video, expanded sample schedule, and editing controls in one place, making corrections faster and less error-prone.

Command:

```bash
uv run glasskit eval review --eval-dir eval
```

To jump directly to a failure reported by a separate eval run, include its case, target, and timestamp:

```bash
uv run glasskit eval review --eval-dir eval --case task-01 --target step_1 --time 7.4
```

The command opens a local browser UI where you can compare labeled moments with their source video and add, move, edit, or delete samples. Changes are saved automatically to the case file.

### Run One Case While Debugging

Goal: run a focused eval and print every sample result.

Command:

```bash
uv run glasskit eval run --case task-01 --target step_1 --verbose --keep-going --save-failures --output-json eval/runs/results.json --artifacts-dir eval/runs/artifacts
```

Expected output: focused case and target progress, every selected sample result, a final summary, gate results, a per-target table, and a failures table when any sample fails or errors.

Note: `--keep-going` records adapter evaluation errors and comparison errors as sample results instead of aborting on the first sample error. `--save-failures` writes JPEG frames and per-result JSON for failed or errored samples. Treat `eval/runs/` as disposable output and add it to your app repo's `.gitignore` if you keep generated eval reports out of source control.

### Enforce CI Quality Gates

Goal: make the command fail when quality drops below your threshold.

Command:

```bash
uv run glasskit eval run --min-pass-rate 0.9 --min-target-pass-rate 0.85 --max-failures 3 --output-json eval/runs/results.json
```

Expected behavior: the process exits `0` when every gate passes, `1` when the eval ran but one or more gates failed, and `2` for setup or runtime errors that abort the run.

Note: Threshold defaults are intentionally unset. Without `--min-pass-rate`, `--min-target-pass-rate`, `--max-failures`, or YAML thresholds, failed comparisons are visible in the report but do not fail the command. Always configure a gate for CI.

### Use an Adapter Config File

Goal: pass runtime settings to your adapter without putting them in case files.

Command:

```bash
uv run --env-file .env glasskit eval run --adapter-config eval/local-adapter.yaml
```

Example `eval/local-adapter.yaml`:

```yaml
api_url: https://example.test/v1
model: vision-checker
jpeg_quality: 90
```

Note: `--adapter-config` must be a YAML or JSON object. `glasskit eval` does not expand environment variables inside this file. Read secrets from environment variables in your adapter.

## Eval Directory Layout

A typical layout keeps the eval directory and adapter code in the app repo while storing recordings outside the repo:

```text
recordings/
  task-01.mp4
  task-02.mp4
your-app-repo/
  eval/
    adapter.py
    config.yaml # Optional eval config file
    cases/
      task-01.yaml # Case file
      task-02.yaml
```

You can also keep videos next to the case file and reference them with a local filename such as `video: task-01.mp4`. Tip: You may not want to commit large media files to a regular Git repository because of their size. Consider cloud object storage or Git LFS instead.

The `video:` path in the case file is resolved relative to that file.

The eval config file is optional and supports eval-level `thresholds`. It must be named `config.yaml`. Case files must live directly under `cases/` and use the `.yaml` suffix. Supported video suffixes are `.mp4`, `.mov`, `.m4v`, `.webm`, and `.mkv`. Timestamps in case files are seconds from the start of the decoded clip.

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
    - at: [4.0, 6.0]
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
| `video` | Yes | Video path resolved relative to the case file's directory. |
| `description` | No | Human-readable case note. |
| `sampling.every_s` | No | Default range sampling interval in seconds. Defaults to `0.5`; must be greater than `0`. |
| `workflow.targets` | No | Optional advanced target metadata list for imported or generated workflow definitions. |
| `targets` | Yes | Mapping of target id to target definition. Must contain at least one target. |
| `thresholds` | No | Case-level gates: `min_pass_rate`, `max_failures`, and `per_target.<target>.min_pass_rate`. Omitted keys create no gate for that key. |

Target fields:

| Field | Required | Description |
| --- | ---: | --- |
| `label` | No | Display name shown in reports. |
| `config` | No | Adapter-specific metadata for the target. Use this as the default place for prompt IDs, rubric IDs, reference assets, confidence thresholds, or other target-specific settings. Defaults to an empty object. Values override matching keys from `workflow.targets`. |
| `samples` | Yes | List of sample blocks. Empty lists are invalid unless `--allow-empty` is used. |

Most evals should put adapter metadata directly under `targets.<id>.config`. `workflow.targets` is useful when an eval is generated from or synchronized with an app workflow manifest and workflow-owned metadata should stay separate from eval-owned samples, expectations, and per-case overrides. Each workflow target needs an `id`; `label` and extra metadata keys are allowed. Entries are matched by `id`, then merged into the adapter target config before `targets.<id>.config` is applied:

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
| `expect` | Yes | JSON-like expected value: `null`, boolean, finite number, string, array, or object with string keys. |
| `every_s` | No | Per-block range sampling interval. Defaults to `sampling.every_s` for the case, which defaults to `0.5`. |
| `field` | No | Dot-separated path to extract from the adapter observation before comparison. When omitted, the whole observation is compared. |
| `compare` | No | Comparison config with `mode` and optional `tolerance`. When omitted, mode is inferred from `expect` and numeric tolerance is `0.0`. |
| `comment` | No | Human-readable note retained with the expectation. It does not affect adapter calls or comparison. |
| `ignore` | No | Nonempty reason for ignoring this block. Ignored samples are reported but are not decoded, sent to the adapter, or included in pass rates, failure counts, or quality gates. |

Sample times must be finite and nonnegative. Ranges must have `end` greater than `start`. Overlapping or duplicate samples for the same target are invalid. Expansion is capped at 10,000 samples across all targets in one case; pathological ranges are rejected before their samples are materialized.

Use `ignore` for a known exceptional sample that should remain documented without affecting a run. An ignored `at` list or `range` ignores every expanded sample in that block; use a single `at` timestamp when only one sample is exceptional.

## Comparison Reference

The adapter observation and the sample `expect` value must both be JSON-like. For simple checks, return the value you want compared and omit `field`. Use `field` when the adapter already returns a structured observation that should be preserved in JSON output or saved failure artifacts, such as `matches`, `confidence`, `reason`, or detected classes in one object. When `field` is present, `glasskit eval` extracts that nested value first and compares the extracted value against `expect`.

Field paths are dot-separated. Mapping keys are matched by name, and list indexes can be addressed with nonnegative numeric path parts such as `detections.0.label`. Missing fields fail the sample with a `missing field: ...` reason.

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

By default, `glasskit eval run` loads `<eval-dir>/adapter.py:create_evaluator`. With the default eval directory, that is `eval/adapter.py:create_evaluator`.

Use `--adapter <module-or-file>:<callable>` to choose another adapter target. The module side can be an import path such as `my_app.eval_adapter` or a file path such as `eval/adapter.py`. The callable side can name a function, class, or nested attribute such as `create_evaluator` or `EvalAdapters.step_checker`.

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

Adapter factories may be synchronous or asynchronous. No-argument factories are supported, but they do not receive `AdapterConfig`. If the factory needs `--adapter-config`, `--artifacts-dir`, `--verbose`, or the eval directory, define it with one required argument.

### Individual and Batch Evaluation

An evaluator chooses one of two execution strategies by implementing `evaluate` or `evaluate_many`. Both methods may be synchronous or asynchronous.

| Strategy | Adapter method | GlassKit execution | Use when |
| --- | --- | --- | --- |
| Individual | `evaluate(sample, target)` | Calls the method once per sample, with at most `--concurrency` calls in flight for the current target. | Each sample maps to an independent request or local operation. This is the recommended default for ordinary model APIs. |
| Batch | `evaluate_many(samples, target)` | Calls the method once per target with all of that target's decoded samples. GlassKit does not schedule the samples inside the batch. | The provider has a real multi-input endpoint, or the adapter can materially reuse work across the target's samples. |

Implement at least one strategy. If an evaluator implements both methods, `evaluate_many` takes precedence. Batch evaluation must return exactly one JSON-like observation per input sample in the same order. A batch adapter owns any chunking or internal concurrency it needs; `--concurrency` does not fan out calls inside `evaluate_many`.

Samples with an `ignore` reason are omitted before either strategy runs. They are not decoded and are not present in the `samples` list passed to `evaluate_many`.

Prefer `evaluate` when the work consists of independent calls, even if those calls should overlap. GlassKit bounds the concurrency, supports both async methods and synchronous methods run through worker threads, and restores deterministic sample order after calls finish. With `--keep-going`, an individual call failure becomes an error only for that sample.

Use `evaluate_many` only for actual batch behavior. If a batch call fails, GlassKit cannot attribute the failure to one input, so `--keep-going` records an error for every sample in that target batch.

The optional `close()` method is called after the run or adapter validation check and may also be synchronous or asynchronous.

Simple function adapters are also supported when the first two positional argument names are either `image, target_id` or `sample, target`:

```python
def evaluate_frame(image, target_id):
    return target_id == "step_1"
```

Factory `config` fields:

| Field | Description |
| --- | --- |
| `eval_dir` | Resolved eval directory path. |
| `config` | Mapping loaded from `--adapter-config`, or an empty mapping. |
| `artifacts_dir` | Path from `--artifacts-dir`, or `None`. |
| `verbose` | Boolean from `--verbose`. |

Sample fields passed to the evaluator:

| Field | Description |
| --- | --- |
| `image` | Decoded RGB `PIL.Image.Image` for the nearest decoded frame at the requested timestamp. |
| `timestamp_s` | Requested sample timestamp in seconds from the start of the clip, from `at` or the expanded `range`. |
| `frame_index` | Zero-based decoded video frame index chosen for that timestamp. |
| `sample_index` | Case-local sample index. |
| `video_path` | Source video path as a string. |
| `case_name` | Case filename stem. |

Frame sampling is timestamp-based. `sample.timestamp_s` is always the requested eval time, not the actual media timestamp of the selected frame. `sample.image` is the decoded frame whose timestamp is closest to that requested time, with ties choosing the earlier frame. For variable-frame-rate videos, `glasskit eval` uses each decoded frame's presentation time when available; if a video lacks frame timestamps, it falls back to `frame_index / average_rate`.

Target fields passed to the evaluator:

| Field | Description |
| --- | --- |
| `id` | Target id from the case file. |
| `index` | Target's zero-based order in the case file. |
| `label` | Optional target label. |
| `config` | Adapter-specific target metadata from `targets.<id>.config`, plus any matching optional metadata from `workflow.targets`. |

Adapter return values must be JSON-like: `None`, boolean, finite number, string, array, or object with string keys.

## Command Reference

Every command supports `--help`.

### `glasskit`

Purpose: top-level command group.

```bash
glasskit --help
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--install-completion` | None | Install shell completion for the current shell. |
| `--show-completion` | None | Print shell completion setup text. |
| `--help` | None | Show help and exit. |

Commands:

| Command | Description |
| --- | --- |
| `eval` | Recorded-video eval tools. |

### `glasskit eval`

Purpose: command group for recorded-video evals.

```bash
glasskit eval --help
```

Commands:

| Command | Description |
| --- | --- |
| `run` | Decode frames, call the adapter, compare observations, apply gates, and report results. |
| `validate` | Validate eval structure, videos, sample times, and optional adapter construction. |
| `list-samples` | Print the expanded sample schedule. |
| `review` | Open the local browser UI for inspecting and correcting timed expectations. |

### `glasskit eval review`

Purpose: launch the local eval review UI without loading or running an adapter.

```bash
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

The video is a browser preview and may show an adjacent frame. Playback support depends on the source codec and browser; `glasskit eval run` evaluates the requested timestamps independently of the preview.

Exit behavior: exits `0` after a normal `Ctrl+C` shutdown and `2` for an invalid eval path or selector, invalid option combination, missing packaged assets, or bind failure. Failure to open the browser is nonfatal because the printed URL remains usable.

### `glasskit eval run`

Purpose: execute eval samples and apply quality gates.

```bash
glasskit eval run --case task-01 --output-json eval/runs/results.json
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--adapter TEXT` | `<eval-dir>/adapter.py:create_evaluator` | Adapter target in `<module-or-file>:<callable>` form. |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--case TEXT` | All cases | Only run one case by filename or stem. Do not include path separators. |
| `--target TEXT` | All targets | Only run one target id from the selected cases. May be used with or without `--case`. |
| `--adapter-config PATH` | None | YAML or JSON object passed to the adapter factory as `AdapterConfig.config`. |
| `--concurrency INTEGER` | `1` | Maximum concurrent per-sample `evaluate` calls within a target. Must be greater than zero. Ignored for adapters using `evaluate_many`, which control their own batch execution. |
| `--min-pass-rate FLOAT` | None | Run-level pass-rate gate from `0.0` to `1.0`. Overrides eval-level `thresholds.min_pass_rate` and suppresses case-level gates when set. |
| `--min-target-pass-rate FLOAT` | None | Uniform per-target pass-rate gate from `0.0` to `1.0` for targets present in the selected results. Replaces eval-level `thresholds.per_target` gates. |
| `--max-failures INTEGER` | None | Run-level maximum failed comparisons. Overrides eval-level `thresholds.max_failures` and suppresses case-level gates when set. |
| `--keep-going` | `false` | Record adapter evaluation or comparison errors as sample results and continue. |
| `--verbose` | `false` | Print every sample result and set `AdapterConfig.verbose`. |
| `--output-json PATH` | None | Write a machine-readable JSON report. |
| `--artifacts-dir PATH` | None | Base directory for generated artifacts. Failure artifacts are written under its `failures/` subdirectory; when omitted, they are written under `<eval-dir>/runs/failures/`. |
| `--save-failures` | `false` | Save failed or errored sample frames and per-result JSON. |
| `--max-failures-to-print INTEGER` | `20` | Maximum number of failed or errored results printed in the final failures table. Use `0` to hide table rows. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

Exit behavior: exits `0` when every gate passes, `1` when the eval ran but one or more gates failed, and `2` when setup or runtime errors abort the run.

### `glasskit eval validate`

Purpose: validate an eval directory without evaluating sample observations.

```bash
glasskit eval validate --adapter eval/adapter.py:create_evaluator
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--adapter TEXT` | None | Optional adapter target to import, construct, and close. |
| `--case TEXT` | All cases | Only validate one case by filename or stem. |
| `--target TEXT` | All targets | Only validate one target id from the selected cases. May be used with or without `--case`. |
| `--adapter-config PATH` | None | YAML or JSON object passed to the adapter factory during adapter validation. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

Exit behavior: exits `0` when validation passes and `1` when validation fails.

### `glasskit eval list-samples`

Purpose: print expanded sample rows.

```bash
glasskit eval list-samples --case task-01
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--case TEXT` | All cases | Only list one case by filename or stem. |
| `--target TEXT` | All targets | Only list one target id from the selected cases. May be used with or without `--case`. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

Exit behavior: exits `0` when the samples can be listed and `2` when the eval directory cannot be loaded.

## Configuration

`glasskit eval` has no global config file. Eval configuration lives in the eval config file and case files within the eval directory.

Default values at a glance:

| Area | Default When Omitted |
| --- | --- |
| Eval directory | `eval` from the command's working directory. |
| `run` adapter target | `<eval-dir>/adapter.py:create_evaluator`. |
| Individual evaluation concurrency | `1`. Increase with `run --concurrency`. |
| `<eval-dir>/config.yaml` | Optional. Missing file means no eval-level thresholds. |
| Case `sampling.every_s` | `0.5` seconds. |
| Sample block `every_s` | Inherits the case `sampling.every_s`. |
| Sample `field` | Compares the whole adapter observation. |
| Sample `compare.mode` | Inferred from `expect`: non-boolean numbers use `numeric`; booleans, strings, `null`, arrays, and objects use `exact`. |
| Numeric `compare.tolerance` | `0.0`. |
| `targets.<id>.config` | Empty object. Use this as the default place for adapter-specific target metadata. The final adapter target config also includes matching optional metadata from `workflow.targets`, with `targets.<id>.config` taking precedence. |
| Threshold keys | Unset. Missing `min_pass_rate`, `max_failures`, and `per_target.<target>.min_pass_rate` keys create no corresponding gate. |
| Adapter config | Empty object unless `--adapter-config` is provided. |
| Failure artifacts | Saved only with `--save-failures`; default directory is `<eval-dir>/runs/failures/`. |

`<eval-dir>/config.yaml` currently supports only eval-level thresholds:

```yaml
thresholds:
  min_pass_rate: 0.9
  max_failures: 5
  per_target:
    step_1:
      min_pass_rate: 0.95
```

All threshold keys default to unset. `glasskit eval` does not treat a missing `min_pass_rate` as `1.0`, `0.0`, or the current pass rate; it skips that pass-rate gate. If every threshold is omitted, ordinary failed comparisons still appear in the console report and JSON output, but they do not fail `glasskit eval run`. If another gate is configured, such as `max_failures` or a per-target `min_pass_rate`, ordinary failed comparisons can still fail the run through that gate. Adapter evaluation errors, non-JSON adapter observations, and unexpected comparison exceptions abort the run with exit code `2` by default. With `--keep-going`, those sample-level errors are recorded as results with status `error`, and the automatic `adapter_errors` gate makes the completed run fail with exit code `1`. Adapter setup, loading, and close errors still abort the command.

Threshold precedence:

| Source | Applies To | Notes |
| --- | --- | --- |
| `--min-pass-rate` | Selected run | Overrides eval-level `thresholds.min_pass_rate`. When set, case-level gates are not applied. |
| `--max-failures` | Selected run | Overrides eval-level `thresholds.max_failures`. When set, case-level gates are not applied. |
| `--min-target-pass-rate` | Selected run targets | Adds the same per-target pass-rate gate for each target present in the selected results and replaces eval-level `thresholds.per_target` gates. Case-level gates still apply unless `--min-pass-rate` or `--max-failures` is set. |
| `<eval-dir>/config.yaml` | Selected run | Applies after CLI overrides. Eval-level per-target gates for targets outside a `--case` or `--target` filtered run are skipped. |
| `cases/<case>.yaml` `thresholds` | That case | Applies per case unless `--min-pass-rate` or `--max-failures` is set. |

Other precedence rules:

| Area | Rule |
| --- | --- |
| Range sampling | A sample block's `every_s` overrides case-level `sampling.every_s`. |
| Target metadata | `targets.<id>.config` is the default place for adapter target metadata and overrides matching keys from optional `workflow.targets` metadata. |
| Adapter config | `--adapter-config` is independent of the eval config file and case files and is passed only to the adapter factory. |

## Environment Variables

`glasskit eval` defines no CLI-specific environment variables and does not read from stdin.

Adapters may read any environment variables your app needs, such as API keys, backend URLs, or feature flags. Keep secrets out of case files and adapter config files. With `uv`, pass a dotenv file to `uv run`:

```bash
uv run --env-file .env glasskit eval run
```

## Output Formats

Human-readable output is printed with Rich tables to stdout. JSON output is written only when `--output-json` is provided; it is written to the requested file, not stdout.

`glasskit eval run --output-json eval/runs/results.json` writes a JSON file with this shape:

```json
{
  "eval_dir": "/absolute/path/to/eval",
  "cases": ["task-01"],
  "success": true,
  "summary": {
    "evaluated": 1,
    "passed": 1,
    "failed": 0,
    "errors": 0,
    "ignored": 0,
    "pass_rate": 1.0,
    "duration_seconds": 0.42,
    "evaluation_timing_mode": "individual",
    "average_evaluation_seconds_per_sample": 0.31,
    "throughput_samples_per_second": 2.38
  },
  "gates": [
    {
      "name": "adapter_errors",
      "passed": true,
      "message": "no adapter/comparison errors"
    }
  ],
  "results": [
    {
      "case": "task-01",
      "target": "step_1",
      "target_label": "Step 1",
      "sample_index": 0,
      "timestamp_s": 0.0,
      "status": "passed",
      "expected": true,
      "observed": {
        "matches": true
      },
      "observed_value": true,
      "compare_mode": "exact",
      "field": "matches",
      "reason": "matched",
      "source": "at",
      "evaluation_duration_seconds": 0.31,
      "evaluation_timing_mode": "individual",
      "artifact_image": null,
      "artifact_json": null
    }
  ]
}
```

Ignored samples remain in the `results` array with status `ignored`, their ignore reason in `reason`, and null observation and evaluation-timing fields. The summary's `evaluated` count, pass rate, timing, throughput, and quality gates exclude those results.

`--save-failures` writes artifacts for failed or errored sample results. By default, files go under `<eval-dir>/runs/failures/`. When `--artifacts-dir` is provided, failure files go under `<artifacts-dir>/failures/`. Each saved result includes a JPEG frame and a JSON metadata file named with the case, target, sample index, and timestamp.

## Exit Codes

| Code | Meaning | Fix |
| ---: | --- | --- |
| `0` | Command succeeded. For `run`, every gate passed. | No action needed. |
| `1` | Validation failed, or `run` completed but one or more gates failed. | Read the validation issues or gate table, fix the eval, adapter, or quality threshold, then rerun. |
| `2` | A CLI usage error, setup error, config error, video error, adapter loading error, or adapter runtime error aborted the command. | Read the error message, validate the eval directory, and rerun with `--keep-going` if you want sample-level adapter evaluation errors recorded instead of aborting. |

## Errors and Troubleshooting

Start with validation:

```bash
uv run glasskit eval validate
```

Then inspect samples and run one case:

```bash
uv run glasskit eval list-samples --case task-01
uv run glasskit eval run --case task-01 --target step_1 --verbose --keep-going
```

Common failures:

| Message or Symptom | Likely Cause | Fix |
| --- | --- | --- |
| `eval directory does not exist` | `--eval-dir` points at the wrong path. | Run from the app repo or pass the correct `--eval-dir`. |
| `cases directory does not exist` | `<eval-dir>/cases/` is missing. | Add case files under `cases/` and reference videos from them. |
| `no case files found` | No case files exist under `cases/`, or `--case` does not match a case filename or stem. | Check the case filename or stem. |
| `no eval targets found` | `--target` does not match any target id in the selected cases. | Check the target id in the case file or broaden the case filter. |
| `invalid schema` | A YAML field name, type, value, or structure is invalid. | Compare the file against the Case File Reference. Extra fields are rejected except extra metadata inside `workflow.targets` items. |
| `video file does not exist` | The case `video:` path is wrong. | Resolve it relative to the case file's directory, not the shell working directory. |
| `unsupported video file type` | Video suffix is not one of `.mp4`, `.mov`, `.m4v`, `.webm`, or `.mkv`. | Convert or rename to a supported container type. |
| `could not open video` or `could not decode video` | PyAV cannot read the file. | Check that the file is a real video and can be decoded locally. |
| `sample ... exceeds video duration` | A timestamp is beyond the readable video duration. | Fix the timestamp units or shorten the sampled range. |
| `overlaps` or `duplicates` | Sample blocks for one target overlap. | Adjust ranges and `at` timestamps so each target has distinct labeled samples. |
| `exceeds the per-case expansion limit` | A range cadence or total schedule would expand beyond 10,000 samples. | Increase the cadence, shorten the range, or split the workflow into separate cases. |
| Browser preview is unavailable | The browser cannot play the source container or codec, even though PyAV may be able to probe it. | Use source inspection and editing when enabled, or convert a copy to a browser-supported codec; the review command does not transcode. |
| `adapter must be '<module-or-file>:<callable>'` | `--adapter` is not in target form. | Use a value such as `eval/adapter.py:create_evaluator`. |
| `adapter file does not exist` | The adapter file path is wrong. | Check the path from the command working directory. |
| `adapter import failed` | Adapter dependencies or app imports are unavailable. | Run from the app repo, install dependencies, set `PYTHONPATH`, or pass environment variables needed during import. |
| `adapter target not found` | The module imported, but the callable path does not exist. | Check the function, class, or nested attribute name after `:`. |
| `adapter ... did not return an object with evaluate(...) or evaluate_many(...)` | The factory returned the wrong shape. | Return an object implementing an individual or batch evaluation strategy, or use a supported simple function adapter. |
| `adapter returned non-JSON observation` | The adapter returned a dataclass, SDK object, image, bytes, infinite number, or other non-JSON value. | Return only JSON-like values. |
| `adapter returned N observations for M samples` | `evaluate_many` returned the wrong number of observations. | Return exactly one observation per input sample in order. |
| `missing field: result.matches` | `field` does not exist in the adapter observation. | Update the adapter output or the sample `field`. |
| `invalid_observation: adapter returned null` | The adapter returned `None` for a sample expecting a non-null value. | Return a JSON value matching the expected shape, or set `expect: null`. |
| Failed comparisons but exit code `0` | No quality gate was configured. | Add `--min-pass-rate`, `--max-failures`, `--min-target-pass-rate`, or YAML thresholds. |

## Support

Questions, bug reports, feature requests, and pull requests are welcome. Use whichever path is easiest:

- Discord: https://discord.gg/v5ayGKhPNP
- GitHub issues and pull requests: https://github.com/RealComputer/GlassKit

For a real app-backed setup, see [this example](https://github.com/RealComputer/GlassKit/tree/main/examples/origami/backend).
