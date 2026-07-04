# GlassKit CLI

`gk` is the GlassKit command-line package. Its first command family is `gk eval`, a recorded-video evaluator for smart-glasses apps.

Are you tired of manually repeating physical vision-enabled smart glasses app test over and over? `gk eval` is for you! You prepare video recording for the target workflow, YAML file describing how it's processed at specific timestamps, and an app adapter that connects this cli and your app. And you can do an automatic eval/test for your vision part of you app!

The current implementation assumes you have a `uv` managed pipeline. If your use case does not fit the current model, please open an issue. We want to expand support based on real app needs.

## Install

Use the CLI from the app repository that contains the eval suite, adapter, app dependencies, and environment files. With `uv`, install the published `gk` package into the command environment and invoke the `gk` console script in one command:

```bash
cd path/to/your-app
uv run --with gk gk eval --help
```

If you already installed the command another way (`uv add --dev gk`), you can drop the `uv run --with gk` prefix and run `gk eval ...` directly.

Run help when you need the exact options for the installed version:

```bash
uv run --with gk gk --help
uv run --with gk gk eval --help
uv run --with gk gk eval run --help
```

Pass app environment files or extra runtime settings through `uv` in the same command:

```bash
uv run --with gk --env-file .env gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite
```

## Quick Start

Create a starter case from a video:

```bash
uv run --with gk gk eval init-case \
  --suite eval-suite \
  --case fold-step-001 \
  --video path/to/recording.mp4 \
  --target step_1 \
  --label "Step 1"
```

Edit `eval-suite/fold-step-001/expected.yaml` so the sample timestamps and expected values match the video. Validate the suite before running a model-backed adapter:

```bash
uv run --with gk gk eval validate --suite eval-suite
uv run --with gk gk eval list-samples --suite eval-suite
```

Run the eval with an adapter:

```bash
uv run --with gk gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite \
  --min-pass-rate 0.9 \
  --output-json tmp/eval-results.json \
  --save-failures \
  --artifacts-dir tmp/eval-artifacts
```

The command exits `0` when all quality gates pass, `1` when the eval ran but one or more gates failed, and `2` for setup or runtime errors such as invalid YAML, unreadable videos, or adapter failures that are not being collected with `--keep-going`.

## Eval Suite Layout

An eval suite is a directory containing one or more case directories. Each case has an `expected.yaml` file and either one video file in the case directory or a `video:` path in `expected.yaml`.

```text
eval-suite/
  fold-step-001/
    video.mp4
    expected.yaml
  fold-step-002/
    camera-recording.mov
    expected.yaml
```

A single-case suite is also supported by placing `expected.yaml` directly in the suite directory.

Supported video suffixes are `.mp4`, `.mov`, `.m4v`, `.webm`, and `.mkv`. Timestamps in `expected.yaml` are seconds from the start of the clip, even when the container stores non-zero presentation timestamps internally.

## Writing `expected.yaml`

Here is a representative case file:

```yaml
version: 1
video: video.mp4
description: Fold step 1 should be detected after the crease is completed.
sampling:
  every_s: 0.5
workflow:
  targets:
    - id: step_1
      label: Step 1
      prompt_id: origami.step_1
targets:
  step_1:
    label: Step 1
    config:
      reference_image: assets/step_1.png
    samples:
      - range: [0.0, 6.8]
        expect: false
      - range: [7.4, 11.8]
        expect: true
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

Ranges are interpreted as `[start, end)`. With `sampling.every_s: 0.5`, `range: [7.4, 8.6]` expands to samples at `7.4`, `7.9`, and `8.4` seconds. Only declared `range` and `at` samples are evaluated; unlabeled gaps are skipped. A sample block must contain exactly one of `range` or `at`.

Use ranges for stable windows where the expected answer should be unchanged. Use `at` for isolated moments or when a transition is too short to sample safely. Avoid labeling ambiguous transition frames unless the ambiguity is exactly what you want to measure.

### Case Fields

- `version` must be `1`.
- `video` is an optional path to the case video, resolved relative to the case directory. If it is omitted, the case directory must contain exactly one supported video file.
- `description` is optional and only for humans.
- `sampling.every_s` sets the default sample interval for `range` blocks in the case. The default is `0.5` seconds.
- `workflow.targets` is optional metadata matched to targets by each entry's `id`. Each entry must have `id`; `label` is optional; extra fields are passed to the adapter as `target.config` unless overridden by `targets.<id>.config`.
- `targets.<target_id>.label` is optional display text for reports.
- `targets.<target_id>.config` is optional adapter-specific metadata for that target. This is where you can put prompt ids, reference image paths, class names, or other app-level data that the core CLI should not know about.
- `targets.<target_id>.samples` is the required list of labeled sample blocks.
- `thresholds` is optional case-level gating. It can contain `min_pass_rate`, `max_failures`, and `per_target.<target_id>.min_pass_rate`.

## Expected Values And Comparison

The adapter returns a JSON-like value: `null`, boolean, number, string, array, or object. Each sample's `expect` value is compared with that returned value.

By default, booleans, strings, and `null` use exact comparison. Numbers use numeric comparison with zero tolerance unless you set one. Arrays and objects use exact comparison unless you choose another mode.

Use `field` when the adapter returns a structured object but the sample only cares about one nested value:

```yaml
targets:
  detector:
    samples:
      - at: 2.0
        field: result.matches
        expect: true
```

Field paths are dot-separated. Mapping keys are matched by name, and list indexes can be addressed with non-negative numeric path parts such as `detections.0.label`.

Supported `compare.mode` values are:

```yaml
targets:
  score:
    samples:
      - at: 1.0
        expect: 0.75
        compare:
          mode: numeric
          tolerance: 0.05
  metadata:
    samples:
      - at: 1.0
        expect:
          result:
            matches: true
        compare:
          mode: json_subset
  objects:
    samples:
      - at: 1.0
        expect: ["paper", "crease"]
        compare:
          mode: set_contains_all
```

- `exact` requires the observed value to equal `expect`.
- `numeric` requires both values to be numbers and allows `tolerance`.
- `json_subset` requires every key and value in `expect` to be present in the observed object. For arrays, each expected item must match at least one observed item.
- `set_equals` compares arrays as unordered sets.
- `set_contains_any` passes when at least one expected array item is present in the observed array.
- `set_contains_all` passes when every expected array item is present in the observed array.

## Suite-Level Thresholds

Put thresholds that should apply to every case in `suite.yaml` or `eval.yaml` at the suite root:

```yaml
thresholds:
  min_pass_rate: 0.9
  max_failures: 5
  per_target:
    step_1:
      min_pass_rate: 0.95
    step_2:
      min_pass_rate: 0.85
```

Every run also includes an `adapter_errors` gate. The run only succeeds if the adapter produced no runtime or comparison errors and every configured quality gate passed.

Failed comparisons are intentionally controlled by quality gates instead of a built-in default failure policy. If you run without `--min-pass-rate`, `--min-target-pass-rate`, `--max-failures`, or YAML thresholds, failed comparisons are reported in the summary and JSON output but do not make the command exit nonzero; adapter, runtime, or comparison errors still fail through the `adapter_errors` gate. Configure a pass-rate or max-failures gate for CI or any run where failed observations should fail the command.

CLI gates are useful for one-off CI jobs or local experiments:

```bash
uv run --with gk gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite \
  --min-pass-rate 0.9 \
  --min-target-pass-rate 0.85 \
  --max-failures 3
```

`--min-pass-rate` and `--max-failures` override suite-level YAML values for the run. Because those flags define a run-level pass/fail policy, case-level YAML gates are not applied when either flag is set. `--min-target-pass-rate` applies the same target pass-rate gate to every target present in the selected results. With `--case`, suite-level per-target gates for targets outside the selected case are skipped.

## Commands

### `gk eval init-case`

`init-case` creates a case directory, copies the source video into it when needed, and writes a starter `expected.yaml`:

```bash
uv run --with gk gk eval init-case \
  --suite eval-suite \
  --case fold-step-001 \
  --video recordings/fold-step-001.mp4 \
  --target step_1 \
  --label "Step 1"
```

The case name must be a single directory name under the suite. If the source video is already inside the case directory, the generated `video:` path is written relative to the case directory. Use `--force` to overwrite an existing `expected.yaml` or case video.

### `gk eval validate`

`validate` checks suite structure, YAML schema, video readability, sample timestamps, and optional adapter importability:

```bash
uv run --with gk gk eval validate --suite eval-suite
uv run --with gk gk eval validate --suite eval-suite --adapter eval_adapter.py:create_evaluator
uv run --with gk gk eval validate --suite eval-suite --case fold-step-001
```

Use validation before long or paid model evals. It catches most local mistakes without sending frames to a backend, unless you pass `--adapter`.

### `gk eval list-samples`

`list-samples` prints the expanded sample schedule:

```bash
uv run --with gk gk eval list-samples --suite eval-suite
uv run --with gk gk eval list-samples --suite eval-suite --case fold-step-001
```

This is the quickest way to confirm that your ranges, point samples, fields, and explicit comparison modes expand as intended. When a sample omits `compare.mode`, the Mode column is blank because the default mode is inferred when the sample is evaluated.

### `gk eval run`

`run` decodes sample frames, calls the adapter, compares results, applies gates, prints a summary, and optionally writes JSON and failure artifacts:

```bash
uv run --with gk gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite \
  --case fold-step-001 \
  --adapter-config adapter-config.yaml \
  --keep-going \
  --verbose \
  --output-json tmp/eval-results.json \
  --save-failures \
  --artifacts-dir tmp/eval-artifacts
```

- `--case` limits the run to one case directory by name.
- `--adapter-config` reads a YAML or JSON object and passes it to the adapter factory.
- `--keep-going` records adapter or comparison errors as errored sample results instead of aborting the run on the first error.
- `--verbose` prints every sample result as it is produced and sets `AdapterConfig.verbose` for the adapter.
- `--output-json` writes a machine-readable report with summary counts, elapsed run duration, gate results, and per-sample observations. The final console summary also shows the elapsed duration.
- `--save-failures` saves failed sample frames and per-result JSON files. If `--artifacts-dir` is omitted, artifacts are written under `.gk-artifacts` in the suite directory.
- `--allow-empty` allows suites or cases with no samples. This is mainly useful while drafting a suite, not for real quality gates.

## Writing An Adapter

An adapter is the bridge between the generic CLI and your app. It receives decoded video frames plus target metadata, calls your app or model backend, and returns a JSON-like observation for each sample.

Pass an adapter as `<module-or-file>:<callable>`. The module side can be a Python import path such as `my_app.eval_adapter` or a file path such as `eval_adapter.py`. The callable side can name a function, class, or nested attribute such as `create_evaluator` or `EvalAdapters.fold_checker`.

The recommended shape is a factory that accepts one required `AdapterConfig` argument and returns an evaluator object:

```python
from __future__ import annotations

from typing import Any


def create_evaluator(config: Any) -> "FoldEvaluator":
    raw_config = dict(config.config)
    return FoldEvaluator(
        api_key=raw_config["api_key"],
        model=raw_config.get("model", "default-model"),
        verbose=bool(config.verbose),
    )


class FoldEvaluator:
    def __init__(self, *, api_key: str, model: str, verbose: bool) -> None:
        self._api_key = api_key
        self._model = model
        self._verbose = verbose

    async def evaluate(self, sample: Any, target: Any) -> bool:
        image = sample.image
        target_id = target.id
        prompt_id = target.config.get("prompt_id", target_id)
        return await call_model_backend(
            api_key=self._api_key,
            model=self._model,
            image=image,
            prompt_id=prompt_id,
            timestamp_s=sample.timestamp_s,
        )

    async def close(self) -> None:
        await close_model_client()
```

No-argument factories and evaluator classes are also supported, but they will not receive `AdapterConfig`. If the factory needs `--adapter-config`, `--artifacts-dir`, `--verbose`, or the suite path, give it one required argument.

`evaluate(sample, target)` may be synchronous or asynchronous. If the evaluator also implements `evaluate_many(samples, target)`, the runner calls it once per target and uses the returned list as the observations for that target's samples. `evaluate_many` must return exactly one observation for each input sample in the same order.

`close()` is optional and may be synchronous or asynchronous. Use it to close HTTP clients, model sessions, or temporary resources.

### Adapter Inputs

`AdapterConfig` has these fields:

- `suite_path` is the resolved path to the eval suite.
- `config` is the object loaded from `--adapter-config`; it is an empty mapping when the option is omitted.
- `artifacts_dir` is the path from `--artifacts-dir`, or `None` when the option is omitted.
- `verbose` mirrors `--verbose`.
- `sample` has these fields:
- `image` is a decoded RGB `PIL.Image.Image` for the requested timestamp.
- `timestamp_s` is the requested sample timestamp in seconds from the start of the clip.
- `frame_index` is the decoded video frame index chosen for that timestamp.
- `sample_index` is the case-local sample index.
- `video_path` is the source video path as a string.
- `case_name` is the case directory name.
- `target` has these fields:
- `id` is the target id from `expected.yaml`.
- `index` is the target's zero-based order in the case file.
- `label` is the optional target label.
- `config` is the merged target metadata from `workflow.targets` and `targets.<id>.config`.

### Simple Function Adapters

For smoke checks or fake local evals, the adapter target can be a function whose first two positional arguments are either `image, target_id` or `sample, target`:

```python
def evaluate_frame(image, target_id):
    return target_id == "step_1"
```

```python
async def evaluate_sample(sample, target):
    return {
        "target": target.id,
        "bright": sample.image.convert("L").getextrema()[1] > 180,
    }
```

Function adapters are useful for testing suite wiring because they do not need a model backend. Production adapters should usually use the object shape so they can reuse clients and close resources cleanly.

### Adapter Config Files

Use `--adapter-config` for values that should not live in `expected.yaml`, such as backend URLs, model names, thresholds owned by the adapter, or local asset paths:

```yaml
api_url: "https://example.test/v1"
model: "vision-checker"
jpeg_quality: 90
```

The CLI only parses the file as YAML or JSON and passes the resulting object to `AdapterConfig.config`; it does not expand environment variables inside the file. Read secrets directly from environment variables in the adapter and use `--adapter-config` for non-secret runtime settings.

### Adapter Return Values

Return the smallest stable value that answers the target. For a binary detector, return `true` or `false`. For a classifier, return a string label. For richer workflows, return an object and use `field` or `json_subset` in `expected.yaml`.

Good observations are deterministic, JSON-like, and easy to inspect in the JSON report:

```python
return {
    "result": {
        "matches": True,
        "confidence": 0.94,
        "label": "folded",
    }
}
```

Avoid returning SDK objects, dataclasses, images, bytes, or other values that cannot be serialized to JSON. They make reports harder to read and may fail when written to `--output-json`.

## Practical Adapter Pattern

A model-backed adapter usually follows this flow:

```python
def create_evaluator(config):
    settings = dict(config.config)
    return MyEvaluator(
        api_key=settings.get("api_key") or os.environ["MODEL_API_KEY"],
        api_url=settings.get("api_url", "https://api.example.test"),
        model=settings.get("model", "vision-model"),
    )


class MyEvaluator:
    def __init__(self, *, api_key, api_url, model):
        self._client = make_async_client(api_key=api_key, base_url=api_url)
        self._model = model

    async def evaluate_many(self, samples, target):
        return [await self.evaluate(sample, target) for sample in samples]

    async def evaluate(self, sample, target):
        prompt = target.config.get("prompt", f"Check {target.id}.")
        image_payload = encode_image(sample.image)
        response = await self._client.check(
            model=self._model,
            prompt=prompt,
            image=image_payload,
        )
        return parse_response(response)

    async def close(self):
        await self._client.aclose()
```

Keep retries, response parsing, prompt construction, and backend-specific error handling in the adapter. Keep generic eval semantics in `expected.yaml` and the CLI.

## Debugging Failed Runs

Start with validation:

```bash
uv run --with gk gk eval validate --suite eval-suite --adapter eval_adapter.py:create_evaluator
```

Then list samples and run one case:

```bash
uv run --with gk gk eval list-samples --suite eval-suite --case fold-step-001
uv run --with gk gk eval run --suite eval-suite --case fold-step-001 --adapter eval_adapter.py:create_evaluator --verbose
```

If the adapter is unstable or expensive, add `--keep-going --save-failures --output-json tmp/eval-results.json`. The saved failure images show exactly what frame the adapter saw, and the JSON report includes the raw observation, extracted field, comparison mode, and reason for each sample.

Common issues:

- `adapter target not found` means the `<module-or-file>:<callable>` path imported successfully but the callable name could not be resolved.
- `adapter import failed` usually means the working directory, `PYTHONPATH`, or app environment does not include the adapter's dependencies.
- `video file does not exist` means the `video:` path is wrong or is being resolved from the case directory differently than expected.
- `sample ... exceeds video duration` means a timestamp is beyond the readable video duration. Check the recording length and the units in `expected.yaml`.
- `missing field` means the adapter returned a value that does not contain the sample's `field` path.
- `invalid_observation: adapter returned null` means the adapter returned `None` for a sample whose expected value was not `null`.

## Technical detail

For internal details, please check [ANGETS.md](ANGETS.md).
