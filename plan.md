# GlassKit CLI Eval Plan

## Goal

Build a reusable recorded-video evaluation tool for GlassKit apps. The first practical target is `examples/origami`, where prompt and fold-check changes currently require repeated physical runs on Rokid Glasses, but the design should also fit later apps such as `rokid-overshoot-openai-realtime` and `rokid-rfdetr` once they get their own adapters and eval suites.

The proposed public package name is `gk`. The Python module should be `gk`, the repo directory should be `cli`, and the primary console command should be `gk`. The recorded-video evaluator should be implemented as the `gk eval` subcommand family from the start.

The PyPI name `glasskit` is already taken. Reserving `gk` gives GlassKit a short top-level CLI namespace that can later grow beyond eval without renaming this tool.

## Terms

Use these terms consistently:

- Eval suite: the directory passed to the CLI. It contains one or more evaluation cases.
- Case: one video plus its expected results YAML. A case may cover one origami step, several targets from the same video, or a longer clip.
- Target: the generic unit that the CLI asks the adapter to evaluate. In origami, a target maps naturally to a folding step such as `step_1`. In a task graph or object-detection app, a target can map to a detector, graph node, split, inventory scan, or other stable app-defined id.
- Sample: one timestamped frame, or one expanded timestamp inside a labeled range.
- Expectation: the expected value and comparison config for a sample or range.
- Observation: the adapter or model output before comparison.
- Result: the pass, fail, ignored, or error outcome after comparing an observation with an expectation.
- Gate: an aggregate threshold that controls process success, such as a minimum pass rate.

## Non-goals

- Do not auto-generate `expected.yaml` with a stronger and slower VLM in the first version. Manual expected ranges are the source of truth for now.
- Do not require a physical Rokid device during CLI execution. Creating useful eval videos may still require a real run, but evaluation should run from files.
- Do not make the CLI responsible for app-specific model prompts, recipe logic, RF-DETR classes, Overshoot payload parsing, or workflow-transition policy. Those belong in adapters and reusable app modules.
- Do not require a 100% pass rate by default. The CLI should support strict gates, but noisy vision tests need configurable thresholds.
- Do not test full session transitions, auto-advance, or continuous full-run workflow state in the MVP. This tool should first evaluate model observations on recorded frames or clips. A higher-level session replay test can be added later if needed.

## Current Code Findings

- `examples/origami` is server-authoritative. The Android app streams camera video to the FastAPI backend, and the backend owns session phase, step index, HUD state, auto-check enablement, Overshoot prompt switching, and step advancement.
- Origami step definitions already live in `examples/origami/backend/assets/origami_steps.json`. Each step has a stable `id`, title, HUD image, reference image, and prompt.
- Origami uses Overshoot v1beta for the live app path. The backend creates an Overshoot stream, publishes backend-composed camera/reference frames into the returned LiveKit room, waits for frame ingestion, and calls `/chat/completions` against `ovs://streams/<stream_id>?frame_index=-1`.
- Origami composes images before sending them to Overshoot: the raw camera frame is converted to a PIL image, a reference-image header is added by `_compose_reference_image`, and the composed image is published through the LiveKit video source.
- Origami currently records the pre-composition camera frames sent into the Overshoot path. `ORIGAMI_RECORD_OVERSHOOT_INPUTS=true` writes session MP4s under `backend/debug/overshoot-inputs` by default. This is a good starting point for eval cases because the offline evaluator can reuse the same reference composition code.
- `examples/origami/overshoot-docs.md` contains the local Overshoot docs snapshot for the current API. It documents both stream references such as `ovs://streams/<id>?frame_index=-1` and ordinary chat-completion image/video content such as `data:image/jpeg;base64,...`.
- Origami result parsing is intentionally strict. The chat-completion prompt asks for exactly `true` or `false`, the runtime stores that text under `result`, and `_parse_overshoot_boolean` only accepts booleans or the strings `"true"` and `"false"` from that field.
- Origami step advancement is not identical to one-frame evaluation. The live state machine ignores stale results, waits through a 0.6 second settle window after step entry, requires two consecutive true results, marks the step done, then auto-advances after 2.0 seconds. This transition policy should stay in the live app for now rather than becoming part of the eval CLI MVP.
- `rokid-overshoot-openai-realtime` already needs richer observations than origami. It parses structured JSON and evaluates booleans, enums, numeric thresholds, repeated rising edges, inventory lists, and recipe step state.
- `rokid-rfdetr` has a clean split between model observation and workflow state: `VisionProcessor` returns `DetectionResult.detected_classes`, and `SpeedrunController` applies the two-hit split completion rule.

## Design Principle

The CLI should own generic recorded-video mechanics: eval-suite discovery, video decoding, sample scheduling, expectation expansion, adapter loading, comparison, reporting, and quality gates.

Each app should own app-specific observation logic through a small adapter. The adapter is responsible for using the same prompts, reference images, model clients, parsers, and workflow helpers that the live runtime uses. This keeps the CLI reusable and avoids baking Overshoot, OpenAI, RF-DETR, origami, or recipe-specific concepts into the core package.

The MVP should evaluate model observations, not full live sessions. In concrete terms, for each expected sample the CLI calls the adapter with a decoded frame or batch of frames and a target context, receives a JSON-like observation, and compares it with the expected value.

## Package Layout

Add a new package under `cli/`.

```text
cli/
  pyproject.toml
  README.md
  src/gk/
    __init__.py
    cli.py
    eval/
      __init__.py
      adapters.py
      compare.py
      expectations.py
      models.py
      report.py
      runner.py
      video.py
  tests/
    eval/
      test_expectations.py
      test_compare.py
      test_adapter_loading.py
      test_runner_fake_adapter.py
```

Use a normal `pyproject.toml` console-script entry point.

```toml
[project]
name = "gk"
version = "0.1.0"
description = "GlassKit command-line tools"
requires-python = ">=3.12"
dependencies = [
  "av",
  "pillow",
  "pydantic>=2",
  "pyyaml",
  "rich",
  "typer",
]

[project.scripts]
gk = "gk.cli:app"

[dependency-groups]
dev = [
  "pytest",
  "ruff",
  "ty",
]

[build-system]
requires = ["uv_build"]
build-backend = "uv_build"
```

`[project.scripts]` is what makes the installed executable exist. The `gk = "gk.cli:app"` entry means installing the package creates a `gk` command that imports `gk.cli` and calls `app`.

`[build-system]` tells Python packaging tools how to build the package into installable artifacts. Here it says to install `uv_build` at build time and use it as the build backend.

Recommended runtime dependencies are `av` for video decoding, `pillow` for RGB frame images, `pydantic` for schema validation, `pyyaml` for human-authored YAML, `rich` for CLI output, and `typer` for multi-command CLI ergonomics. Keep `rich` isolated to `gk/eval/report.py` and CLI presentation; `runner.py`, `compare.py`, `expectations.py`, and `video.py` should be usable without terminal formatting concerns.

Do not add app/model SDKs to the core package. In particular, the reusable CLI package should not depend on FastAPI, aiortc, OpenAI SDKs, Overshoot app code, Roboflow, RF-DETR, PyTorch, `inference`, OpenCV, or MoviePy. Those dependencies belong in app adapters or target backend projects.

## Invocation Model

The tool is a normal Python package named `gk` with a console script named `gk`. The normal published-package invocation should be `uv run --with gk gk eval ...`, run from the target app project or backend directory. This works better than isolated `uvx` for this use case because adapters often need to import the target backend's local modules and use the target backend's lockfile.

For an external app after `gk` is published:

```bash
cd my-glasses-app/backend
uv run \
  --with gk \
  --env-file .env \
  gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite
```

For local GlassKit development before publishing, run the local CLI package in editable mode from the target backend project. This fixes the import-path issue because the backend directory becomes the current working directory, so `eval_adapter.py` can import modules such as `src.origami_config` and `src.rendering` naturally.

```bash
cd examples/origami/backend
uv run \
  --with-editable ../../../cli \
  --env-file .env \
  gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite
```

If a repo-root command is needed, explicitly set the backend import path.

```bash
PYTHONPATH=examples/origami/backend \
uv run \
  --project examples/origami/backend \
  --with ./cli \
  --env-file examples/origami/backend/.env \
  gk eval run \
  --adapter examples/origami/backend/eval_adapter.py:create_evaluator \
  --suite examples/origami/backend/eval-suite
```

An isolated tool run is still possible for adapters that have no local app imports or when all app dependencies are explicitly added to the tool environment, but it should not be the primary documented workflow for app evaluation.

## Publishing Plan

Reserve the `gk` PyPI name early with a minimal but real package once the `cli` skeleton exists. The first published version can expose `gk --help` and `gk eval --help` before the full evaluator is complete, but it should not be an empty placeholder. This keeps the package name available while still giving early external users a normal install path.

## CLI Commands

- `gk eval run`: run all cases in an eval suite, print live progress, print a summary, and exit non-zero if any quality gate fails.
- `gk eval validate`: validate expected-result YAML, video file references, adapter importability, target references, and expanded sample counts without running model evaluation.
- `gk eval list-samples`: print the expanded sample schedule for debugging labels and transition windows.
- `gk eval init-case`: optional helper that creates a case directory with a starter `expected.yaml` for a video.

The MVP only needs `run` and `validate`; `list-samples` is very useful if expectation ranges are confusing, so it should be implemented early if it is cheap.

Important `run` options should include `--adapter`, `--suite`, `--case` for filtering by case name, `--adapter-config` for a YAML or JSON config file passed to the adapter, `--min-pass-rate`, `--min-target-pass-rate`, `--max-failures`, `--keep-going`, `--verbose`, `--output-json` for machine-readable results, `--artifacts-dir`, `--save-failures`, and `--max-failures-to-print`.

## Adapter Protocol

The adapter target is a Python file or import path plus callable, such as `eval_adapter.py:create_evaluator`, `examples/origami/backend/eval_adapter.py:create_evaluator`, or `origami_eval:create_evaluator`.

The callable receives an `AdapterConfig` and returns an evaluator object. The evaluator may be synchronous or asynchronous. The core protocol should be small and JSON-oriented, with frames standardized as RGB `PIL.Image.Image` instances.

```python
from collections.abc import Mapping
from typing import Any, Protocol
from PIL import Image

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

class FrameSample:
    image: Image.Image
    timestamp_s: float
    frame_index: int
    sample_index: int
    video_path: str
    case_name: str

class TargetContext:
    id: str
    index: int
    label: str | None
    config: Mapping[str, Any]

class FrameEvaluator(Protocol):
    async def evaluate(self, sample: FrameSample, target: TargetContext) -> JSONValue: ...
    async def close(self) -> None: ...
```

Support a simple function adapter as sugar: if the loaded callable has the signature `evaluate_frame(image, target_id)` or `evaluate_frame(sample, target)`, wrap it in a `FrameEvaluator`. This keeps the first origami adapter easy while still allowing richer stateful adapters later.

Also support optional batch hooks for services where per-frame setup is expensive.

```python
class BatchFrameEvaluator(FrameEvaluator, Protocol):
    async def evaluate_many(self, samples: list[FrameSample], target: TargetContext) -> list[JSONValue]: ...
```

The runner should prefer `evaluate_many` when available and fall back to `evaluate`. This matters for remote VLM adapters, where batching can reuse an HTTP client, share prompt setup, control concurrency, and optionally benefit from provider-side prompt caches.

For clip-level models, add a later optional protocol rather than forcing it into the first frame protocol.

```python
class ClipEvaluator(Protocol):
    async def evaluate_clip(self, clip: ClipSample, target: TargetContext) -> JSONValue: ...
```

## Eval Suite Format

An eval suite directory contains any number of case directories. Each case directory contains one video and one `expected.yaml`.

```text
eval-suite/
  fold-step-001/
    video.mp4
    expected.yaml
  fold-step-002/
    video.mp4
    expected.yaml
```

`expected.yaml` may explicitly name the video, or the CLI may default to the only supported video file in the case directory. Explicit `video` is preferred but should be optional when there is exactly one supported video file.

Non-essential fields should be optional. Required data should be minimal: the CLI needs to find a video, find targets, expand samples, and know expected values for non-ignored samples. `version`, `description`, `sampling`, `label`, `workflow`, `thresholds`, `field`, and `compare` should all have defaults or be optional.

```yaml
version: 1
video: video.mp4
description: First origami prompt eval after a fold-check prompt update.
sampling:
  interval_s: 0.2
targets:
  step_1:
    label: Step 1
    default:
      expect: false
    samples:
      - range: [0.0, 6.8]
        expect: false
      - range: [7.4, 11.8]
        expect: true
      - range: [6.8, 7.4]
        mode: ignore
  step_2:
    samples:
      - range: [12.0, 18.4]
        expect: false
      - range: [19.0, 23.6]
        expect: true
      - range: [18.4, 19.0]
        mode: ignore
```

Ranges use seconds from the start of the video and should be interpreted as `[start, end)` so adjacent ranges do not double-sample the boundary. `interval_s` defaults to `0.2` at the case level, but individual sample blocks may override it with `every_s`.

Use `mode: ignore` for ambiguous transition windows where hands occlude the object, the fold is in motion, or a human would not confidently label the frame. Ignored samples should be counted in eval-suite diagnostics but excluded from pass-rate gates.

For sparse targets, support exact timestamps.

```yaml
targets:
  step_3:
    samples:
      - at: [31.0, 31.2, 31.4]
        expect: true
      - at: 34.0
        expect: false
```

For structured outputs, support field paths and comparison modes.

```yaml
targets:
  inventory_scan:
    samples:
      - range: [0.0, 4.0]
        expect:
          ingredients: ["orange juice", "lime"]
        compare:
          mode: json_subset
  pour_gatorade:
    samples:
      - range: [12.0, 18.0]
        field: level
        expect: 0.5
        compare:
          mode: numeric
          tolerance: 0.1
  sushi_split_1:
    samples:
      - range: [5.0, 9.0]
        field: detected_classes
        expect: ["rice", "nori"]
        compare:
          mode: set_contains_all
```

## Target Definitions

The CLI should not require a global workflow registry, but it should allow optional metadata. Target keys such as `step_1` are enough for origami. A case or eval suite may optionally include metadata if an adapter needs richer configuration.

```yaml
workflow:
  targets:
    - id: step_1
      label: Step 1
      app_ref: step_1
    - id: fold_complete_detector
      label: Fold complete detector
      app_ref: detector.fold_complete
```

For `examples/origami`, the adapter can load `assets/origami_steps.json` and map target ids to `OrigamiStep` objects. The eval file should still use stable ids instead of numeric indexes because ids survive insertions and reordering better.

## Comparison Semantics

The comparison layer should accept JSON-like values only. Supported initial modes should be `exact`, `numeric`, `json_subset`, `set_equals`, `set_contains_any`, and `set_contains_all`.

The default mode is inferred from the expected value: booleans and strings use `exact`, numbers use `numeric` with zero tolerance unless a tolerance is specified, arrays and objects require an explicit comparison mode unless the implementation can make a conservative exact comparison. Being conservative by default avoids hidden false passes.

`field` uses dotted paths into dict-like outputs, such as `result.matches`, `ingredients`, or `detected_classes`. If the field is missing, the sample fails with a clear reason. If the adapter returns `None`, the sample fails as `invalid_observation` unless the expectation explicitly allows `null`.

## Runner Algorithm

1. Load and validate CLI options.
2. Load the adapter factory and create one evaluator per run.
3. Discover case directories under the eval-suite path.
4. Parse each `expected.yaml` and expand ranges into timestamped sample expectations.
5. Validate that each case has at least one non-ignored sample and that timestamps fit inside the video duration.
6. Decode frames with PyAV. Seek by timestamp for sparse schedules, and prefer sequential decode for dense schedules.
7. For each case and target, call `evaluate_many` when available; otherwise call `evaluate` for each sample.
8. Compare observed values with expected values and record pass/fail/ignored/error results.
9. Print progress while running, with failures shown immediately and verbose per-sample output behind `--verbose`.
10. Aggregate results by case, target, comparison mode, and expected value, then apply quality gates and exit with status code `0` or `1`.

The runner should keep sample order deterministic: cases sorted by directory name, targets in YAML order, samples by timestamp.

## Progress and Summary Output

During a run, print the current case, video, target, sample count, and pass/fail progress. In normal mode, avoid printing every passing sample; print failures as they happen with timestamp, target id, expected value, observed value, and reason.

At the end, print a summary table with total samples, ignored samples, passed samples, failed samples, pass rate, and gate status. Also print a per-target table and a small failure list capped by `--max-failures-to-print`, defaulting to 20.

Example final shape:

```text
Eval suite: examples/origami/backend/eval-suite
Cases: 2 passed, 1 failed
Samples: 438 evaluated, 27 ignored, 399 passed, 39 failed
Pass rate: 91.1% (gate: >= 90.0%, passed)

By target
step_1  96.4%  108/112
step_2  88.7%   94/106  failed gate >= 90.0%
```

## Quality Gates

Quality gates should be configurable in YAML and overridable by CLI flags.

```yaml
thresholds:
  min_pass_rate: 0.9
  max_failures: 20
  per_target:
    step_1:
      min_pass_rate: 0.95
    step_2:
      min_pass_rate: 0.9
```

CLI flags should include `--min-pass-rate`, `--max-failures`, `--min-target-pass-rate`, and `--allow-empty`. Eval-suite thresholds are useful for repeatable local and CI runs; CLI flags are useful while tuning prompts.

The process should exit non-zero for schema errors, adapter import errors, video decode errors, adapter runtime errors unless `--keep-going` is set, and failed quality gates.

## Origami Integration Plan

Add an origami adapter at `examples/origami/backend/eval_adapter.py`. It should load `assets/origami_steps.json`, map each target id to the existing `OrigamiStep`, reuse the existing reference images, compose the same model input image used by the live Overshoot path, call the selected runtime model backend, and return the parsed boolean observation.

Before writing the adapter, refactor the live origami backend slightly so shared logic has public names and no test-specific duplication. Good candidates are a new `src/fold_check.py` or `src/origami_evaluation.py` module with `compose_fold_check_image(camera, reference, label="Reference shape")`, `parse_fold_check_result(payload)`, and `load_fold_check_steps(path)`. The LiveKit publisher path in `overshoot_runtime.py` and the adapter should both call `compose_fold_check_image`; `session_manager` and the adapter should both call `parse_fold_check_result`.

The live origami path should remain stream-based because it keeps a current frame available for low-latency auto-check prompts. The eval path has a different constraint: deterministic recorded media samples are already available as local frames.

The eval adapter should not recreate the live stream pipeline unless we specifically want to test streaming ingestion. Overshoot can be used through `/chat/completions` without streaming video, so the adapter should compose each sampled frame locally and send it directly as an `image_url` data URL such as `data:image/jpeg;base64,...`. This removes LiveKit setup, stream readiness polling, keepalive, stream cleanup, and frame/result alignment from the eval path.

For short motion-sensitive checks, add clip-level support later. The default origami MVP should stay single-frame because fold completion is a visual state check and the existing expected YAML is timestamp/range based.

Origami should keep the live two-true advancement policy in `session_manager.py`; the recorded-video observation test should not duplicate that policy in the MVP. Add a later session-replay test only after the frame/clip observation tests are useful and stable.

## Eval Suite Creation Workflow for Origami

Use the existing recording path first. Run the app with `ORIGAMI_RECORD_OVERSHOOT_INPUTS=true`, perform a fold step, then copy the generated MP4 from `backend/debug/overshoot-inputs` into a case directory. Because the current recorder starts per Overshoot generation, a full run may produce one MP4 per step; the initial eval-suite format can handle separate cases per step.

It is also fine for an eval video to contain multiple origami steps. The MVP still focuses on evaluating model observations at labeled time ranges, not verifying that the workflow automatically transitions through those steps.

Manually label expected ranges in `expected.yaml`. Prefer broad stable windows and explicit ignored transition windows over dense point-by-point labels. For origami, use `false` for frames where the current target is not yet complete, `true` for stable frames where it clearly matches the reference, and `ignore` for folding motion, occlusion, and hard-to-see frames.

Real eval suites should not be committed directly to this repository unless they are small, public demonstration assets. Keep realistic videos local or in external storage until there is a storage policy, possibly with Git LFS or an artifact bucket.

## Support for Later Examples

The CLI core should be capable of covering `rokid-overshoot-openai-realtime` and `rokid-rfdetr` once those apps get adapters and eval suites, but we do not need to modify those apps or run their evals now.

For `rokid-overshoot-openai-realtime`, a future adapter should return structured JSON observations from the active detector, such as `{"ingredients": [...]}`, `{"color": "blue"}`, `{"level": 0.42}`, or `{"flag": true}`. The comparison layer should then use field paths, numeric tolerance, enum equality, and JSON subset comparisons.

For `rokid-rfdetr`, a future adapter should reuse `VisionProcessor` or its model-loading/inference helper and return `{"detected_classes": [...]}` plus optional labels. Eval cases can use `set_contains_all`, `set_contains_any`, or `set_equals` depending on how strict each split should be.

The first CLI should not know about recipe selection, speech, HUD rendering, or RF-DETR split completion. Those are workflow-level concerns and should be tested later through a separate session replay layer that consumes recorded observations or adapter observations.

## Test Strategy for the CLI Package

Use pytest for the CLI package tests. Add it as a dev dependency with `uv add --dev pytest` from `cli` once the package exists.

Unit-test expectation parsing and range expansion, including `[start, end)` boundaries, per-block `every_s`, ignored windows, sparse timestamps, invalid overlaps, optional YAML fields, and out-of-duration timestamps.

Unit-test comparison modes with booleans, enums, numbers with tolerance, missing fields, object subsets, and set operations.

Unit-test adapter loading with a temporary file adapter and an import-path adapter. The file-adapter loader should add the adapter file's parent directory to `sys.path` during import so simple local adapters can import sibling modules. The documented local development command should still run from the target backend directory because that is the least surprising way to import backend modules and use backend env files.

Integration-test the runner with a generated tiny MP4 and a fake adapter that returns deterministic values based on timestamp and target id. Do not call paid or remote model APIs in default package tests.

Add one optional origami integration smoke test that validates eval-suite parsing and adapter importability, guarded so it only runs when the required env vars are present.

## Implementation Phases

Phase 1: create the `cli` package, define schemas and types, implement `gk eval validate`, implement video sample expansion and decoding, implement adapter loading, implement fake-adapter pytest tests, and print a basic summary.

Phase 2: implement comparison modes, quality gates, live progress output, `list-samples`, `--verbose`, `--keep-going`, `--output-json`, `--artifacts-dir`, `--save-failures`, and polished failure summaries.

Phase 3: refactor origami shared fold-check helpers, add a no-stream Overshoot chat-completion client for composed frame images, add `examples/origami/backend/eval_adapter.py`, and create the first small origami demonstration eval suite from recorded inputs.

Phase 4: document eval-suite creation and CLI usage in `cli/README.md` and link it from `examples/origami/README.md`.

Phase 5: keep later-example support at the core CLI and adapter-contract level only. Do not modify `rokid-rfdetr` or `rokid-overshoot-openai-realtime` until there is a concrete need to add their adapters and eval suites.

## Decisions

- Local origami evals should call the real runtime model backend so prompt and model behavior are actually tested. Core package tests should use fake adapters and should not require network access or paid APIs.
- Small public demonstration videos can live in the repo if needed, but realistic eval suites should not be committed directly until there is a storage policy.
- Continuous full-run transition testing is out of scope for this tool's MVP. A single eval video may contain multiple app steps or targets, but this tool should focus on model response quality at labeled timestamps.
- Manual timestamps from video time zero plus ignored transition windows are enough for the first useful version.
