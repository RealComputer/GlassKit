# GlassKit Video Evaluation CLI Plan

## Goal

Build a reusable recorded-video evaluation tool for GlassKit apps. The first practical target is `examples/origami`, where prompt and fold-check changes currently require repeated physical runs on Rokid Glasses, but the design should also fit later apps such as `rokid-overshoot-openai-realtime` and `rokid-rfdetr`.

The proposed public name is `glasskit-video-eval`. The Python package name should be `glasskit_video_eval`, and the CLI command should be `glasskit-video-eval`.

## Non-goals for the First Version

- Do not auto-generate `expected.yaml` with a stronger and slower VLM in the first version. Manual expected ranges are the source of truth for now.
- Do not require a physical Rokid device during CLI execution. Fixture creation may still require a real run, but evaluation should run from files.
- Do not make the CLI responsible for app-specific model prompts, recipe logic, RF-DETR classes, Overshoot payload parsing, or step-transition policy. Those belong in adapters and reusable app modules.
- Do not require 100 percent pass rate by default. The CLI should support strict gates, but noisy vision tests need configurable thresholds.

## Current Code Findings

- `examples/origami` is server-authoritative. The Android app streams camera video to the FastAPI backend, and the backend owns session phase, step index, HUD state, auto-check enablement, Overshoot prompt switching, and step advancement.
- Origami step definitions already live in `examples/origami/backend/assets/origami_steps.json`. Each step has a stable `id`, title, HUD image, reference image, and prompt.
- Origami sends composed images to Overshoot: the raw camera frame is converted to a PIL image, a reference-image header is added by `_compose_reference_image`, and the composed video track is sent through `ReferenceCompositeTrack`.
- Origami currently records the pre-composition camera frames sent into the Overshoot path. `ORIGAMI_RECORD_OVERSHOOT_INPUTS=true` writes MP4s under `backend/debug/overshoot-inputs` by default. This is a good starting point for fixtures because the offline evaluator can reuse the same reference composition code.
- Origami result parsing is boolean-only today. `_parse_overshoot_boolean` accepts booleans, boolean strings, JSON strings, and common object fields such as `matches`, `match`, `result`, `value`, and `ok`.
- Origami step advancement is not identical to one-frame evaluation. The live state machine ignores stale results, waits through a 0.6 second settle window after step entry, requires two consecutive true results, marks the step done, then auto-advances after 2.0 seconds.
- `rokid-overshoot-openai-realtime` already needs richer observations than origami. It parses structured JSON and evaluates booleans, enums, numeric thresholds, repeated rising edges, inventory lists, and recipe step state.
- `rokid-rfdetr` has a clean split between model observation and workflow state: `VisionProcessor` returns `DetectionResult.detected_classes`, and `SpeedrunController` applies the two-hit split completion rule.

## Design Principle

The CLI should own generic recorded-video mechanics: fixture discovery, video decoding, sample scheduling, expectation expansion, adapter loading, comparison, reporting, and quality gates.

Each app should own app-specific observation logic through a small adapter. The adapter is responsible for using the same prompts, reference images, model clients, parsers, and workflow helpers that the live runtime uses. This keeps the CLI reusable and avoids baking Overshoot, OpenAI, RF-DETR, origami, or recipe-specific concepts into the core package.

The MVP should evaluate frame observations, not full live sessions. In concrete terms, for each expected sample the CLI calls the adapter with a decoded frame and a step context, receives a JSON-like observation, and compares it with the expected value. A later "session replay" mode can feed observations through a workflow state machine to verify automatic step transitions, but the first high-value test is whether the active visual evaluator returns the expected data on recorded frames.

## Package Layout

Add a new package under `tools/video-eval/`.

```text
tools/video-eval/
  pyproject.toml
  README.md
  src/glasskit_video_eval/
    __init__.py
    cli.py
    adapters.py
    compare.py
    expectations.py
    models.py
    report.py
    runner.py
    video.py
  tests/
    test_expectations.py
    test_compare.py
    test_adapter_loading.py
    test_runner_fake_adapter.py
```

Use a normal `pyproject.toml` script entry point.

```toml
[project.scripts]
glasskit-video-eval = "glasskit_video_eval.cli:app"
```

Recommended dependencies are `av` for video decoding, `pillow` for frame images, `pydantic` for fixture validation, `pyyaml` for YAML, `rich` for progress and summary output, and `typer` for the CLI. Use PyAV instead of OpenCV because this repo already uses `av` for media handling and it avoids adding a large additional computer-vision dependency.

## Invocation Model

The package should be runnable as a distributed CLI.

```bash
uvx --from glasskit-video-eval glasskit-video-eval run --adapter path/to/eval_adapter.py:create_evaluator --dataset path/to/video-fixtures
```

When an adapter imports a target backend and needs that backend's dependencies, run the CLI in an environment that includes both the CLI package and the backend project. During local development in this repo, either of these forms should work after the package exists.

```bash
uvx --from ./tools/video-eval --with-editable examples/origami/backend --env-file examples/origami/backend/.env glasskit-video-eval run --adapter examples/origami/backend/eval_adapter.py:create_evaluator --dataset examples/origami/backend/eval-fixtures
```

```bash
uv run --project examples/origami/backend --with ./tools/video-eval --env-file examples/origami/backend/.env glasskit-video-eval run --adapter examples/origami/backend/eval_adapter.py:create_evaluator --dataset examples/origami/backend/eval-fixtures
```

The second form is useful when the target backend lockfile should control dependency versions. The first form satisfies the `uvx` distribution requirement and is the cleaner user-facing command when the adapter's dependencies are installable.

## CLI Commands

- `glasskit-video-eval run`: run all cases in a dataset directory, print live progress, print a summary, and exit non-zero if any quality gate fails.
- `glasskit-video-eval validate`: validate fixture YAML, video file references, adapter importability, step references, and expanded sample counts without running model evaluation.
- `glasskit-video-eval list-samples`: print the expanded sample schedule for debugging labels and transition windows.
- `glasskit-video-eval init-case`: optional helper that creates a case directory with a starter `expected.yaml` for a video.

The MVP only needs `run` and `validate`; `list-samples` is very useful if expectation ranges are confusing, so it should be implemented early if it is cheap.

Important `run` options should include `--adapter`, `--dataset`, `--case` for filtering by case name, `--adapter-config` for a YAML or JSON config file passed to the adapter, `--min-pass-rate`, `--min-step-pass-rate`, `--max-failures`, `--keep-going`, `--verbose`, `--output-json` for machine-readable results, and `--max-failures-to-print`.

## Adapter Protocol

The adapter target is a Python file or import path plus callable, such as `examples/origami/backend/eval_adapter.py:create_evaluator` or `origami_eval:create_evaluator`.

The callable receives an `AdapterConfig` and returns an evaluator object. The evaluator may be synchronous or asynchronous. The core protocol should be small and JSON-oriented.

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

class StepContext:
    id: str
    index: int
    number: int
    title: str | None
    config: Mapping[str, Any]

class FrameEvaluator(Protocol):
    async def evaluate(self, sample: FrameSample, step: StepContext) -> JSONValue: ...
    async def close(self) -> None: ...
```

Support a simple function adapter as sugar: if the loaded callable has the signature `evaluate_frame(image, step_number)` or `evaluate_frame(sample, step)`, wrap it in a `FrameEvaluator`. This keeps the first origami adapter easy while still allowing richer stateful adapters later.

Also support optional batch hooks for services where per-frame setup is expensive.

```python
class BatchFrameEvaluator(FrameEvaluator, Protocol):
    async def evaluate_many(self, samples: list[FrameSample], step: StepContext) -> list[JSONValue]: ...
```

The runner should prefer `evaluate_many` when available and fall back to `evaluate`. This matters for Overshoot-style streaming, where one stream per step or case may be much cheaper and closer to runtime behavior than one model call per sample.

## Fixture Directory Format

A dataset directory contains any number of case directories. Each case directory contains one video and one `expected.yaml`.

```text
eval-fixtures/
  fold-run-001/
    video.mp4
    expected.yaml
  fold-run-002/
    video.mp4
    expected.yaml
```

`expected.yaml` may explicitly name the video, or the CLI may default to the only supported video file in the case directory. Explicit `video` is preferred because it avoids ambiguity.

```yaml
version: 1
video: video.mp4
description: First full origami run after prompt update.
sampling:
  interval_s: 0.2
steps:
  step_1:
    title: Step 1
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
    default:
      expect: false
    samples:
      - range: [12.0, 18.4]
        expect: false
      - range: [19.0, 23.6]
        expect: true
      - range: [18.4, 19.0]
        mode: ignore
```

Ranges use seconds from the start of the video and should be interpreted as `[start, end)` so adjacent ranges do not double-sample the boundary. `interval_s` defaults to `0.2` at the case level, but individual sample blocks may override it with `every_s`.

Use `mode: ignore` for ambiguous transition windows where hands occlude the object, the fold is in motion, or a human would not confidently label the frame. Ignored samples should be counted in fixture diagnostics but excluded from pass-rate gates.

For sparse checks, support exact timestamps.

```yaml
steps:
  step_3:
    samples:
      - at: [31.0, 31.2, 31.4]
        expect: true
      - at: 34.0
        expect: false
```

For structured outputs, support field paths and comparison modes.

```yaml
steps:
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

## Step Definitions

The CLI should not require a global step registry, but it should allow one. Fixture step keys such as `step_1` are enough for origami. A case or dataset may optionally include step metadata if an adapter needs richer configuration.

```yaml
workflow:
  steps:
    - id: step_1
      number: 1
      title: Step 1
    - id: step_2
      number: 2
      title: Step 2
```

For `examples/origami`, the adapter can load `assets/origami_steps.json` and map fixture keys to `OrigamiStep` objects. The fixture should still use stable step ids instead of numeric indexes because ids survive insertions and reordering better.

## Comparison Semantics

The comparison layer should accept JSON-like values only. Supported initial modes should be `exact`, `numeric`, `json_subset`, `set_equals`, `set_contains_any`, and `set_contains_all`.

The default mode is inferred from the expected value: booleans and strings use `exact`, numbers use `numeric` with zero tolerance unless a tolerance is specified, lists use `set_equals` only when explicitly requested, and objects use `json_subset` only when explicitly requested. Being conservative by default avoids hidden false passes.

`field` uses dotted paths into dict-like outputs, such as `result.matches`, `ingredients`, or `detected_classes`. If the field is missing, the sample fails with a clear reason. If the adapter returns `None`, the sample fails as `invalid_observation` unless the expectation explicitly allows `null`.

## Runner Algorithm

1. Load and validate CLI options.
2. Load the adapter factory and create one evaluator per run.
3. Discover case directories under the dataset path.
4. Parse each `expected.yaml` and expand ranges into timestamped sample expectations.
5. Validate that each case has at least one non-ignored sample and that timestamps fit inside the video duration.
6. Decode frames with PyAV. Seek by timestamp for sparse schedules, and prefer sequential decode for dense schedules.
7. For each case and step, call `evaluate_many` when available; otherwise call `evaluate` for each sample.
8. Compare observed values with expected values and record pass/fail/ignored/error results.
9. Print progress while running, with failures shown immediately and verbose per-sample output behind `--verbose`.
10. Aggregate results by case, step, comparison mode, and expected value, then apply quality gates and exit with status code `0` or `1`.

The runner should keep sample order deterministic: cases sorted by directory name, steps in YAML order, samples by timestamp.

## Progress and Summary Output

During a run, print the current case, video, step, sample count, and pass/fail progress. In normal mode, avoid printing every passing sample; print failures as they happen with timestamp, step id, expected value, observed value, and reason.

At the end, print a summary table with total samples, ignored samples, passed samples, failed samples, pass rate, and gate status. Also print a per-step table and a small failure list capped by `--max-failures-to-print`, defaulting to 20.

Example final shape:

```text
Dataset: examples/origami/backend/eval-fixtures
Cases: 2 passed, 1 failed
Samples: 438 evaluated, 27 ignored, 399 passed, 39 failed
Pass rate: 91.1% (gate: >= 90.0%, passed)

By step
step_1  96.4%  108/112
step_2  88.7%   94/106  failed gate >= 90.0%
```

## Quality Gates

Quality gates should be configurable in YAML and overridable by CLI flags.

```yaml
thresholds:
  min_pass_rate: 0.9
  max_failures: 20
  per_step:
    step_1:
      min_pass_rate: 0.95
    step_2:
      min_pass_rate: 0.9
```

CLI flags should include `--min-pass-rate`, `--max-failures`, `--min-step-pass-rate`, and `--allow-empty`. Dataset thresholds are useful for repeatable local and CI runs; CLI flags are useful while tuning prompts.

The process should exit non-zero for schema errors, adapter import errors, video decode errors, adapter runtime errors unless `--keep-going` is set, and failed quality gates.

## Origami Integration Plan

Add an origami adapter at `examples/origami/backend/eval_adapter.py`. It should load `assets/origami_steps.json`, map each fixture step id to the existing `OrigamiStep`, reuse the existing reference images, compose the same model input image used by the live Overshoot path, call the selected model backend, and return the parsed boolean observation.

Before writing the adapter, refactor the live origami backend slightly so the shared logic has public names and no test-specific duplication. Good candidates are a new `src/fold_check.py` or `src/origami_evaluation.py` module with `compose_fold_check_image(camera, reference, label="Reference shape")`, `parse_fold_check_result(payload)`, and `load_fold_check_steps(path)`. `ReferenceCompositeTrack` and the adapter should both call `compose_fold_check_image`; `session_manager` and the adapter should both call `parse_fold_check_result`.

The current runtime talks to Overshoot through WebRTC streams, not a simple local pure function. The adapter should hide that detail. If Overshoot offers or later adds a single-image API, the origami adapter can call it per sample. If only streaming is available, implement a stateful adapter that creates one Overshoot stream per case or per step, replays the composed frames at the requested cadence, receives structured results, and aligns each result to the nearest sample timestamp. The CLI contract does not need to change for either implementation.

Origami should keep the live two-true advancement policy in `session_manager.py`; the recorded-video observation test should not duplicate that policy in the MVP. Add a later session-replay test only after the frame observation tests are useful and stable.

## Fixture Creation Workflow for Origami

Use the existing recording path first. Run the app with `ORIGAMI_RECORD_OVERSHOOT_INPUTS=true`, perform the fold once, then copy the generated MP4 from `backend/debug/overshoot-inputs` into a case directory. Because the current recorder starts per Overshoot generation, a full run may produce one MP4 per step; the initial fixture format can still handle separate case directories per step.

For better full-run fixtures, add a continuous raw-camera recorder later. That recorder should write one MP4 for the whole session plus an event log containing active step changes, manual controls, and auto-advance events. The event log can become a helper for drafting `expected.yaml`, but it is not required for the MVP.

Manually label expected ranges in `expected.yaml`. Prefer broad stable windows and explicit ignored transition windows over dense point-by-point labels. For origami, use `false` for frames where the current step is not yet complete, `true` for stable frames where it clearly matches the reference, and `ignore` for folding motion, occlusion, and hard-to-see frames.

## Support for Later Examples

For `rokid-overshoot-openai-realtime`, the adapter should return structured JSON observations from the active detector, such as `{"ingredients": [...]}`, `{"color": "blue"}`, `{"level": 0.42}`, or `{"flag": true}`. The fixture comparison layer should then use field paths, numeric tolerance, enum equality, and JSON subset checks.

For `rokid-rfdetr`, the adapter should reuse `VisionProcessor` or its model-loading/inference helper and return `{"detected_classes": [...]}` plus optional labels. Fixtures can use `set_contains_all`, `set_contains_any`, or `set_equals` depending on how strict each split should be.

The first CLI should not know about recipe selection, speech, HUD rendering, or RF-DETR split completion. Those are workflow-level concerns and should be tested later through a separate session replay layer that consumes recorded observations or adapter observations.

## Test Strategy for the CLI Package

Unit-test expectation parsing and range expansion, including `[start, end)` boundaries, per-block `every_s`, ignored windows, sparse timestamps, invalid overlaps, and out-of-duration timestamps.

Unit-test comparison modes with booleans, enums, numbers with tolerance, missing fields, object subsets, and set operations.

Unit-test adapter loading with a temporary file adapter and an import-path adapter.

Integration-test the runner with a generated tiny MP4 and a fake adapter that returns deterministic values based on timestamp and step id. Do not call paid or remote model APIs in default package tests.

Add one optional origami integration smoke test that validates fixture parsing and adapter importability, guarded so it only runs when the required env vars are present.

## Implementation Phases

Phase 1: create the `tools/video-eval` package, define schemas and types, implement `validate`, implement video sample expansion and decoding, implement adapter loading, implement fake-adapter integration tests, and print a basic summary.

Phase 2: implement comparison modes, quality gates, live progress output, `--verbose`, `--keep-going`, and polished failure summaries.

Phase 3: refactor origami shared fold-check helpers, add `examples/origami/backend/eval_adapter.py`, and create the first small origami fixture dataset from existing recorded inputs.

Phase 4: document fixture creation and CLI usage in `tools/video-eval/README.md` and link it from `examples/origami/README.md`.

Phase 5: add adapters for `rokid-rfdetr` and `rokid-overshoot-openai-realtime`, then evaluate whether a session-replay mode is worth adding.

## Open Questions

- Should the first origami adapter call the real remote runtime model during local test runs, or should it support replaying previously captured model outputs for deterministic no-network tests too? My assumption is that local prompt evaluation should call the real small/fast runtime model, while package tests should use fakes.
- Should fixture videos be committed to this repo, stored with Git LFS, or kept as local/private artifacts? My assumption is that only tiny public sample fixtures should live in the repo and realistic videos should stay outside Git until there is a storage policy.
- Do we need one continuous full-run video as the primary origami fixture format immediately, or is one case per recorded step acceptable for the MVP? My assumption is that step-level cases are acceptable first because the current recorder already produces that shape.
- Should timestamps be authored manually from video time zero, or should we add sync markers/event logs before the first implementation? My assumption is manual timestamps plus ignored transition windows are enough for the first useful version.
