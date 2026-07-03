# GlassKit CLI

`gk` is the GlassKit command-line package. The first command family is `gk eval`, a recorded-video evaluator for smart-glasses apps.

The CLI owns generic mechanics: eval-suite discovery, expected-result YAML parsing, timestamp expansion, video decoding, adapter loading, comparison, reporting, artifacts, and quality gates. App-specific prompts, model clients, parsers, and workflow helpers belong in adapters.

## Install During Local Development

Run the CLI from the app backend directory so local adapter imports resolve naturally:

```bash
cd examples/origami/backend
uv run \
  --with-editable ../../../cli \
  --env-file .env \
  gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite
```

For a repo-root run, set the backend import path explicitly:

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

## Eval Suite Format

An eval suite is a directory containing case directories. Each case contains one video and `expected.yaml`.

```text
eval-suite/
  fold-step-001/
    video.mp4
    expected.yaml
```

Example `expected.yaml`:

```yaml
version: 1
video: video.mp4
sampling:
  every_s: 0.5
targets:
  step_1:
    label: Step 1
    samples:
      - range: [0.0, 6.8]
        expect: false
      - range: [7.4, 11.8]
        expect: true
thresholds:
  min_pass_rate: 0.9
```

Ranges are interpreted as `[start, end)`. Only declared `range` and `at` samples are evaluated; unlabeled gaps are skipped.

## Commands

Validate suite structure and adapter importability:

```bash
gk eval validate --adapter eval_adapter.py:create_evaluator --suite eval-suite
```

List expanded samples:

```bash
gk eval list-samples --suite eval-suite
```

Create a starter case from an existing video:

```bash
gk eval init-case \
  --suite eval-suite \
  --case fold-step-001 \
  --video path/to/video.mp4 \
  --target step_1 \
  --label "Step 1"
```

Run evaluation with quality gates and optional failure artifacts:

```bash
gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite \
  --min-pass-rate 0.9 \
  --min-target-pass-rate 0.85 \
  --output-json tmp/eval-results.json \
  --save-failures \
  --artifacts-dir tmp/eval-artifacts
```

## Adapter Contract

The adapter target is a Python file or import path plus callable, such as `eval_adapter.py:create_evaluator` or `my_app.eval:create_evaluator`. The factory receives `AdapterConfig` and returns an object with `evaluate(sample, target)`. If it also implements `evaluate_many(samples, target)`, the runner uses the batch hook.

Simple function adapters are supported for local smoke checks:

```python
def evaluate_frame(image, target_id):
    return target_id == "step_1"
```

Model SDKs and app dependencies should stay out of the core `gk` package. Put those imports in the target app adapter.
