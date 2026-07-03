# GlassKit CLI Development

This package provides the `gk` console command. Its first responsibility is recorded-video evaluation through `gk eval`, but the package name is intentionally broader so future GlassKit CLI tools can share the same namespace.

Keep the core CLI app-agnostic. The core package may handle eval-suite discovery, YAML parsing, timestamp expansion, video decoding, adapter loading, JSON-like comparison, reporting, artifacts, and quality gates. Do not add app/model SDK dependencies such as FastAPI, OpenAI SDKs, Overshoot-specific app code, Roboflow, RF-DETR, PyTorch, OpenCV, or MoviePy to this package; those belong in adapters or target app backends.

The public CLI is for users, so document user workflows in `README.md`. This `AGENTS.md` is for developers changing the CLI internals, tests, packaging, or adapter contract.

Use `uv` from this directory for package work:

- `uv run pytest`: run the CLI tests
- `uv run ruff check .`: lint the CLI package
- `uv run ruff format .`: format the CLI package
- `uv run ty check`: type-check the CLI package
- `uv lock --check`: confirm `uv.lock` matches `pyproject.toml`
- `uv run gk --help` and `uv run gk eval --help`: smoke-check the console entry point

Default tests must not require real glasses recordings, network access, paid model APIs, or a physical Rokid device. Use synthetic videos and fake adapters for committed tests. Local smoke tests may use ignored data under the repository-root `tmp/` directory; the current convention is `tmp/origami-full-run-eval-suite/full-run/video.mp4` with `expected.yaml`.

When testing against the local `tmp` suite, prefer a temporary fake adapter unless the purpose is specifically to test a real model backend. That verifies discovery, validation, timestamp expansion, video decoding, adapter calls, comparison, reporting, and gates without making external API calls.

Keep Markdown prose soft-wrapped. Do not commit generated videos, realistic local recordings, `.venv`, pytest caches, Ruff caches, or `__pycache__` files.
