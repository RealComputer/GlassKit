# GlassKit CLI Development

This package provides the `gk` command. Its first responsibility is recorded-video evaluation through `gk eval`.

- Archtecture Overview: TODO
- README.md is a user facing document. Make it detailed and user-friendly. Examples should assume users are running from their own app repo with commands like `uv run --with gk gk eval ...`. This AGENTS.md is for developers changing the CLI internals, tests, packaging, or adapter contract.
- Keep the core CLI app-agnostic. The core package may handle eval-suite discovery, YAML parsing, timestamp expansion, video decoding, adapter loading, JSON-like comparison, reporting, artifacts, and quality gates. App specific things belong in adapters or target app.
- Default pytest must not require network access or something slow to execute. Use synthetic videos and fake adapters for tests. Committed video fixtures live under `tests/fixtures/`. Keep them reproducible with `tests/fixtures/generate-videos.sh`. Ordinary pytest runs should not require a system `ffmpeg` executable. If a video edge case is worth default coverage, add a committed synthetic fixture for it.

## Key Files

TODO

## Commands

- `uv run ty check && uv run pytest && uv run ruff check --fix && uv run ruff format`: Always run after changes
- `uv run gk --help` and `uv run gk eval --help`: smoke-check the console entry point
- For local testing against the Origami backend, run the CLI from the app backend directory so local adapter imports resolve naturally: `cd REPO-ROOT/examples/origami/backend && uv run --with-editable ../../../cli --env-file .env gk eval run --adapter eval_adapter.py:create_evaluator --suite eval-suite`
