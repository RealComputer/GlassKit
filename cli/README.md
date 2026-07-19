# GlassKit Eval

GlassKit Eval helps you test smart-glasses apps with recorded videos instead of repeated manual runs. Label the moments that matter, connect your app through a language-agnostic adapter, and rerun the same checks locally or in CI.

Use GlassKit Eval through the `glasskit eval` command group. This is its user manual; for contributor implementation notes, see [AGENTS.md](https://github.com/RealComputer/GlassKit/blob/main/cli/AGENTS.md).

## Why Use This?

Smart-glasses apps often guide a wearer through a task. They watch the live camera feed, track workflow progress, and provide the next instruction or correction when it is useful.

These apps are hard to test manually because every prompt, model, or app logic change can mean repeating the same physical workflow. With `glasskit eval`, you provide a workflow recording, label the expected moments, and replay the same checks whenever the app changes.

Use it when you want a reliable way to test the vision path users depend on and enforce quality gates in CI.

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

Start in an app repository checked out next to a `recordings/` directory. This example uses `../recordings/task-01.mp4` from the shell working directory and creates an `eval/` directory in the app repo.

Create the eval directory and write a case file that points at the recording:

```sh
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

```sh
uv run glasskit eval run
```

Expected result: `run` prints case progress, a summary, and a per-target table.

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
    - at: 0.0
      expect: false
YAML
```

Expected result: `eval/cases/task-02.yaml` points to `task-02.mov` in the sibling `recordings/` directory, and the case is ready for timestamp and expectation edits.

Note: If you prefer colocated fixtures, put the recording in `eval/cases/` and set `video:` to the filename, such as `task-02.mov`.

### Validate Before a Run

Goal: catch YAML, video, timestamp, and optional adapter setup problems before calling a paid or slow model backend.

Command:

```sh
uv run glasskit eval validate
```

Expected output:

```text
Validation passed: /absolute/path/to/eval (12 samples)
```

Note: Validation loads the eval directory, probes videos, checks sample timestamps against video duration, and constructs and closes the selected adapter when `--adapter` or `--adapter-command` is provided. It does not evaluate frames.

### Inspect the Expanded Sample Schedule

Goal: confirm that ranges, `at` lists, fields, and compare modes expand as intended.

Command:

```sh
uv run glasskit eval list-samples --case task-01
uv run glasskit eval list-samples --case task-01 --target step_1
```

Expected output: a table with `Case`, `Target`, `Time`, `Expected`, `Mode`, `Field`, and `Source` columns.

Note: Range blocks are half-open intervals. For example, `range: [1.0, 2.0]` with `every_s: 0.5` produces samples at `1.0` and `1.5`, not `2.0`.

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

Note: `--keep-going` records adapter evaluation errors and comparison errors as sample results instead of aborting on the first sample error. `--save-failures` writes JPEG frames and per-result JSON for failed or errored samples. Treat `eval/runs/` as disposable output and add it to your app repo's `.gitignore` if you keep generated eval reports out of source control.

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

Command:

```sh
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

GlassKit Eval supports in-process Python adapters and language-neutral command adapters. Both expose the same individual or batch evaluation behavior to the runner. Use a Python adapter when the app logic is importable by Python, or `--adapter-command` when the adapter should run in its own process, such as a JavaScript or TypeScript backend.

### Python Adapters

By default, `glasskit eval run` loads `<eval-dir>/adapter.py:create_evaluator`. With the default eval directory, that is `eval/adapter.py:create_evaluator`.

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
| Batch | `evaluate_many(samples, target)` | Calls the method once per target with all of that target's decoded samples. GlassKit Eval does not schedule the samples inside the batch. | The provider has a real multi-input endpoint, or the adapter can materially reuse work across the target's samples. |

Implement at least one strategy. If an evaluator implements both methods, `evaluate_many` takes precedence. Batch evaluation must return exactly one JSON-like observation per input sample in the same order. A batch adapter owns any chunking or internal concurrency it needs; `--concurrency` does not fan out calls inside `evaluate_many`.

Samples with an `ignore` reason are omitted before either strategy runs. They are not decoded and are not present in the `samples` list passed to `evaluate_many`. GlassKit Eval schedules the remaining samples in case-file declaration order and passes batch samples in that order.

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

Frame sampling is timestamp-based. `sample.timestamp_s` is always the requested eval time, not the actual media timestamp of the selected frame. `sample.image` is the decoded frame whose timestamp is closest to that requested time, with ties choosing the earlier frame. For variable-frame-rate videos, `glasskit eval` uses each frame's media timestamp when available; if a video lacks frame timestamps, it estimates them from the frame index and average frame rate.

Target fields passed to the evaluator:

| Field | Description |
| --- | --- |
| `id` | Target id from the case file. |
| `index` | Target's zero-based order in the case file. |
| `label` | Optional target label. |
| `config` | Adapter-specific target metadata from `targets.<id>.config`, plus any matching optional metadata from `workflow.targets`. |

Adapter return values must be JSON-like: `None`, boolean, finite number, string, array, or object with string keys.

### Command Adapters

Use `--adapter-command` to launch an adapter in any language that can exchange newline-delimited JSON over standard streams:

```sh
glasskit eval run --adapter-command "node eval/adapter.js"
```

GlassKit Eval parses the command with POSIX shell-style argument quoting and starts it directly without a shell. Pipes, redirects, variable expansion, and command substitution are not supported. The command inherits the working directory and environment, so it can import the app normally and read secrets from environment variables. GlassKit Eval starts one process for each trial, sends `initialize`, sends evaluation requests, sends `close`, and waits for the process to exit. The close response, adapter leader exit, and stdout and stderr drain share a five-second grace period; GlassKit Eval terminates the process tree and reports an adapter error if that complete shutdown sequence does not finish. `glasskit eval validate --adapter-command ...` starts, initializes, closes, and waits for the same process without evaluating frames.

The adapter reads one JSON request per line from stdin and writes one JSON response per line to stdout. Stdout is reserved for protocol messages; write all application and dependency logs to stderr, using `console.error()` in JavaScript. Each message has a 256 MiB limit. Requests have integer ids, and concurrent `evaluate` responses may be returned in any order. GlassKit Eval correlates them by id and restores case-file order in the report.

The command must answer these protocol methods:

| Method | Purpose | Response result |
| --- | --- | --- |
| `initialize` | Construct app clients and declare protocol version `1` plus supported methods. | `{protocolVersion: 1, capabilities: {evaluate, evaluateMany}}` |
| `evaluate` | Evaluate one sample. Sent only when `evaluate` was advertised. | One JSON-like observation. |
| `evaluateMany` | Evaluate every non-ignored sample for one target. Sent when advertised and preferred when both strategies exist. | One JSON-like observation per sample, in order. |
| `cancel` | Best-effort notification that an in-flight request was cancelled. It has no request id and receives no response. | None. |
| `close` | Drain active work, close app clients, acknowledge the request, and exit. | `null`. |

A successful response contains `id` and `result`. A failed request contains the same `id` and an `error` object with a string `message`; an optional `stack` is useful when inspecting the adapter directly. Process startup, initialization, protocol, and shutdown failures abort the eval. An `evaluate` or `evaluateMany` error follows the ordinary adapter error and `--keep-going` behavior.

GlassKit Eval sends adapter configuration with camel-case fields:

| Field | Description |
| --- | --- |
| `evalDir` | Absolute eval directory path. |
| `config` | Object loaded from `--adapter-config`, or an empty object. |
| `artifactsDir` | Absolute path from `--artifacts-dir`, or `null`. |
| `verbose` | Boolean from `--verbose`. |

Command-adapter samples use the same metadata as Python samples, with camel-case names. The image is a lossless PNG represented as `{mimeType, dataBase64, width, height}` on the wire. The JavaScript boilerplate below converts `dataBase64` to `image.bytes`, a Node.js `Buffer`, before calling app code. GlassKit Eval remains responsible for selecting the exact decoded frame; the command should not decode `videoPath` again.

The following complete, dependency-free `eval/adapter.js` is a starting point. The application section at the top is the part to edit: replace `createAppClient` and its methods with thin calls into the app. The factory receives the initialization fields above and returns the supported evaluation methods plus an optional `close`. Application clients stay in the factory's closure, and GlassKit Eval infers capabilities from the returned methods. Keep the marked protocol function unchanged. This example uses an ECMAScript module; use `.mjs` or set `"type": "module"` in the app's `package.json` when needed.

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

    // Implement evaluateMany({ samples, target, signal }) instead when the
    // app has a real multi-input API. If both exist, evaluateMany wins.

    async close() {
      await app.close();
    },
  };
});

// ---- GlassKit Eval protocol boilerplate: copy unchanged below this line. ----
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

  async function close(request) {
    closing = true;
    await Promise.allSettled([...active.values()].map(({ promise }) => promise));
    await respond(request, async () => {
      if (typeof evaluator?.close === "function") await evaluator.close();
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
    if (typeof evaluator?.close === "function") await evaluator.close();
  }
  await outputTail;
}
```

`runGlassKitAdapter` contains the complete protocol boundary, including its state and helpers, so only that one function name shares the module with application code. Its input loop deliberately does not await individual evaluation promises, allowing `--concurrency` requests to overlap. It serializes complete response lines through `outputTail`, so concurrent completions cannot interleave bytes on stdout. A `cancel` notification aborts the request's signal when the app passes that signal through to its backend client. `close` waits for active response handling before releasing resources.

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
| `validate` | Validate eval structure, videos, sample times, and optional adapter construction. |
| `list-samples` | Print the expanded sample schedule. |
| `review` | Open the local browser UI for inspecting and correcting timed expectations. |

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

The video is a browser preview and may show an adjacent frame. Playback support depends on the source codec and browser; `glasskit eval run` evaluates the requested timestamps independently of the preview. The review command does not transcode video, so if the preview is unavailable, continue inspecting and editing the case source without playback or convert a copy to a codec supported by your browser.

Exit behavior: exits `0` after a normal `Ctrl+C` shutdown and `2` for an invalid eval path or selector, invalid option combination, or failure to load or start the review UI. Failure to open the browser is nonfatal because the printed URL remains usable.

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
| `--from FLOAT` | None | Only run expanded samples at or after this time in seconds. Requires `--case`. |
| `--until FLOAT` | None | Only run expanded samples before this time in seconds. Requires `--case`. |
| `--adapter-config PATH` | None | YAML or JSON object passed to the selected adapter in its `config` field. |
| `--concurrency INTEGER` | `1` | Maximum concurrent per-sample `evaluate` calls within a target. Must be greater than zero. Ignored for adapters using `evaluate_many`, which control their own batch execution. |
| `--repeat INTEGER` | `1` | Number of complete executions. Values above `1` run sequential trials with a fresh evaluator for each one. |
| `--min-pass-rate FLOAT` | None | Pass-rate gate from `0.0` to `1.0`. Overrides eval-level `thresholds.min_pass_rate` and suppresses case-level gates when set. |
| `--min-target-pass-rate FLOAT` | None | Uniform per-target pass-rate gate for targets present in the selected results. Replaces eval-level `thresholds.per_target` gates. |
| `--max-failures INTEGER` | None | Maximum failed comparisons. Overrides eval-level `thresholds.max_failures` and suppresses case-level gates when set. |
| `--max-flaky-samples INTEGER` | None | Cross-trial maximum number of samples whose status varies. Must be nonnegative and requires `--repeat` of at least `2`. |
| `--keep-going` | `false` | Record adapter evaluation or comparison errors as sample results and continue. |
| `--verbose` | `false` | Print every sample result and set the factory config object's `verbose` field. |
| `--output-json PATH` | None | Write a machine-readable JSON report. |
| `--artifacts-dir PATH` | None | Base directory for generated artifacts. Failure artifacts are written below its `failures/` subdirectory; when omitted, the base is `<eval-dir>/runs/`. |
| `--save-failures` | `false` | Save failed or errored sample frames and per-result JSON. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

`--from` and `--until` filter the declared expanded sample schedule; they do not create new timestamps. `--from` is inclusive, `--until` is exclusive, either may be used alone, and both require `--case`. Only selected samples are sent to the adapter, and quality gates apply to the selected results.

To test one specific sample, first inspect the schedule, then choose a narrow interval containing only that timestamp. If no other `step_1` sample is declared in the interval, this example runs only the sample at `7.5` seconds:

```sh
glasskit eval run --case task-01 --target step_1 --from 7.5 --until 7.51
```

Exit behavior: exits `0` when every configured gate passes, `1` when the eval completed but one or more gates failed, and `2` when setup or runtime errors abort the run.

### `glasskit eval validate`

Purpose: validate an eval directory without evaluating sample observations.

```sh
glasskit eval validate --adapter eval/adapter.py:create_evaluator
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--adapter TEXT` | None | Optional adapter target to import, construct, and close. |
| `--adapter-command TEXT` | None | Optional NDJSON process adapter command to start, initialize, close, and wait for. Mutually exclusive with `--adapter`. |
| `--case TEXT` | All cases | Only validate one case by filename or stem. |
| `--target TEXT` | All targets | Only validate this target id from the selected cases. Repeat the option to validate multiple targets. Every requested target must exist in the selected case scope. May be used with or without `--case`. |
| `--adapter-config PATH` | None | YAML or JSON object passed to the selected adapter during validation. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

Exit behavior: exits `0` when validation passes and `1` when validation fails.

### `glasskit eval list-samples`

Purpose: print expanded sample rows.

```sh
glasskit eval list-samples --case task-01
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--eval-dir PATH` | `eval` | Eval directory. |
| `--case TEXT` | All cases | Only list one case by filename or stem. |
| `--target TEXT` | All targets | Only list this target id from the selected cases. Repeat the option to list multiple targets. Every requested target must exist in the selected case scope. May be used with or without `--case`. |
| `--from FLOAT` | None | Only list expanded samples at or after this time in seconds. Requires `--case`. |
| `--until FLOAT` | None | Only list expanded samples before this time in seconds. Requires `--case`. |
| `--allow-empty` | `false` | Allow evals or cases with no samples. |

Exit behavior: exits `0` when the samples can be listed and `2` when the eval directory cannot be loaded.

## Configuration

`glasskit eval` has no global config file. Eval configuration lives in the eval config file and case files within the eval directory.

Default values at a glance:

| Area | Default When Omitted |
| --- | --- |
| Eval directory | `eval` from the command's working directory. |
| `run` adapter | Python target `<eval-dir>/adapter.py:create_evaluator`; replaced when `--adapter-command` is set. |
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
| Failure artifacts | Saved only with `--save-failures`; stored below `<eval-dir>/runs/failures/` by default. |

`<eval-dir>/config.yaml` currently supports only eval-level thresholds:

```yaml
thresholds:
  min_pass_rate: 0.9
  max_failures: 5
  per_target:
    step_1:
      min_pass_rate: 0.95
```

All threshold keys default to unset. `glasskit eval` does not treat a missing `min_pass_rate` as `1.0`, `0.0`, or the current pass rate; it skips that pass-rate gate. If every quality threshold is omitted, ordinary failed comparisons still appear in the console report and JSON output, but they do not fail `glasskit eval run`. If another gate is configured, such as `max_failures` or a per-target `min_pass_rate`, ordinary failed comparisons can still fail the run through that gate.

With `--repeat`, quality gates are calculated separately for every trial, and the overall run fails if any trial fails one. Results are never pooled before applying a quality gate. Flaky samples do not fail the run unless `--max-flaky-samples` is configured. A stable failure satisfies `--max-flaky-samples 0`, so combine stability and quality gates when correctness also matters.

Adapter evaluation errors, non-JSON adapter observations, and unexpected comparison exceptions abort the run with exit code `2` by default. With `--keep-going`, those sample-level errors are recorded as results with status `error`, and the automatic `adapter_errors` gate makes the completed run fail with exit code `1`. Adapter setup, loading, and close errors still abort the command.

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
| Target metadata | `targets.<id>.config` is the default place for adapter target metadata and overrides matching keys from optional `workflow.targets` metadata. |
| Adapter config | `--adapter-config` is independent of the eval config file and case files and is passed only to the selected adapter. |

## Environment Variables

`glasskit eval` defines no CLI-specific environment variables and does not read user input from stdin.

Adapters may read any environment variables your app needs, such as API keys, backend URLs, or feature flags. Command adapters inherit the GlassKit Eval process environment, and GlassKit Eval reserves their stdin and stdout for the process protocol. Keep secrets out of case files and adapter config files. With `uv`, pass a dotenv file to `uv run`:

```sh
uv run --env-file .env glasskit eval run
```

## Output Formats

Human-readable output is printed as tables to stdout. JSON output is written to a file when `--output-json` is provided. See the [JSON output reference](https://github.com/RealComputer/GlassKit/blob/main/cli/JSON_OUTPUT.md) for the complete report format, a repeated-run example, and result-structure semantics.

`--save-failures` writes artifacts for every failed or errored sample attempt. To prevent repeated executions from overwriting one another, files are grouped under `<eval-dir>/runs/failures/trial-NNN/` by default or `<artifacts-dir>/failures/trial-NNN/` when `--artifacts-dir` is provided. A run without `--repeat` uses `trial-001`. Each saved result includes a JPEG frame and a JSON metadata file named with the case, target, sample index, and timestamp; the metadata also records its one-based trial number.

## Exit Codes

| Code | Meaning | Fix |
| ---: | --- | --- |
| `0` | Command succeeded. For `run`, every configured gate passed. | No action needed. |
| `1` | Validation failed, or `run` completed but one or more gates failed. | Read the validation issues or gate tables, fix the eval, adapter, threshold, or unstable sample, then rerun. |
| `2` | A CLI usage error, setup error, config error, video error, adapter loading error, or adapter runtime error aborted the command. | Read the error message, validate the eval directory, and rerun with `--keep-going` if you want sample-level adapter evaluation errors recorded instead of aborting. |

## Errors and Troubleshooting

Start with validation:

```sh
uv run glasskit eval validate
```

Then inspect samples and run one case:

```sh
uv run glasskit eval list-samples --case task-01
uv run glasskit eval run --case task-01 --target step_1 --verbose --keep-going
```

## Support

Questions, bug reports, feature requests, and pull requests are welcome. Use whichever path is easiest:

- Discord: https://discord.gg/v5ayGKhPNP
- GitHub issues and pull requests: https://github.com/RealComputer/GlassKit

For a real app-backed setup, see [this example](https://github.com/RealComputer/GlassKit/tree/main/examples/origami/backend).
