# GlassKit CLI Development

This package provides the `gk` console command. Its first responsibility is recorded-video evaluation through `gk eval`, but the package name is intentionally broader so future GlassKit CLI tools can share the same namespace.

Keep the core CLI app-agnostic. The core package may handle eval-suite discovery, YAML parsing, timestamp expansion, video decoding, adapter loading, JSON-like comparison, reporting, artifacts, and quality gates. Do not add app/model SDK dependencies such as FastAPI, OpenAI SDKs, Overshoot-specific app code, Roboflow, RF-DETR, PyTorch, OpenCV, or MoviePy to this package; those belong in adapters or target app backends.

The public CLI is for users, so document user workflows in `README.md`. Public examples should assume users are running from their own app repo with commands like `uv run --with gk gk eval ...`. This `AGENTS.md` is for developers changing the CLI internals, tests, packaging, or adapter contract.

Keep YAML schema validation in `src/gk/eval/schemas.py` with Pydantic models, then convert parsed data into the dataclasses in `src/gk/eval/models.py` and `src/gk/eval/expectations.py`. Do not bypass the schema layer for new eval-suite fields.

When changing `gk eval init-case`, keep generated cases loadable by `load_eval_suite`. Case names must remain a single directory name under the requested suite, and reused in-case videos must be written to `expected.yaml` relative to the case directory.

When changing video decoding, preserve the timing invariants covered by the review fixes: sample timestamps are seconds from the start of the clip, frame PTS values may have a non-zero start offset, and PyAV container duration is expressed in microseconds. Add regression tests for any new seek or duration path.

Use `uv` from this directory for package work:

- `uv run pytest`: run the CLI tests
- `uv run ruff check .`: lint the CLI package
- `uv run ruff format .`: format the CLI package
- `uv run ty check`: type-check the CLI package
- `uv lock --check`: confirm `uv.lock` matches `pyproject.toml`
- `uv run gk --help` and `uv run gk eval --help`: smoke-check the console entry point

For local editable testing against the Origami backend, run the CLI from the app backend directory so local adapter imports resolve naturally:

```bash
cd examples/origami/backend
uv run \
  --with-editable ../../../cli \
  --env-file .env \
  gk eval run \
  --adapter eval_adapter.py:create_evaluator \
  --suite eval-suite
```

For a repo-root Origami run, set the backend import path explicitly and run with the backend project environment:

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

Default tests must not require real glasses recordings, network access, paid model APIs, or a physical Rokid device. Use synthetic videos and fake adapters for committed tests. Local smoke tests may use ignored data under the repository-root `tmp/` directory; the current convention is `tmp/origami-full-run-eval-suite/full-run/video.mp4` with `expected.yaml`.

When testing against the local `tmp` suite, prefer a temporary fake adapter unless the purpose is specifically to test a real model backend. That verifies discovery, validation, timestamp expansion, video decoding, adapter calls, comparison, reporting, and gates without making external API calls.

Committed video fixtures live under `cli/tests/fixtures/`. Keep them tiny, synthetic, public, and reproducible with `cli/tests/fixtures/generate-videos.sh`. Ordinary pytest runs should consume committed files and should not require a system `ffmpeg` executable or generate videos at test runtime. If a video edge case is worth default coverage, add a committed synthetic fixture for it.

Keep Markdown prose soft-wrapped. Do not commit generated videos, realistic local recordings, `.venv`, pytest caches, Ruff caches, or `__pycache__` files.
