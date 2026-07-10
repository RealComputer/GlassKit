# GlassKit CLI Development

This package provides the `glasskit` command. Its current command group is recorded-video evaluation through `glasskit eval`.

`glasskit eval` turns recorded smart-glasses workflows into repeatable evals by sampling labeled video moments, calling an app-provided adapter, comparing JSON-like observations, reporting quality gates for local and CI runs, and reviewing timed expectations in a local browser UI.

## Architecture

- `src/glasskit/cli.py` wires the Typer app and exposes `glasskit eval run`, `validate`, `list-samples`, and `review`.
- The eval pipeline is app-agnostic. `expectations.py` discovers eval directories and case YAML files, loads `config.yaml`, expands case sample blocks, and resolves case videos. `schemas.py` owns Pydantic validation for YAML shape. `video.py` probes and decodes requested frames with PyAV. `adapters.py` imports adapter targets from `module:callable` or `file.py:callable` and normalizes function or object evaluators. `compare.py` evaluates JSON-like observations, and `runner.py` coordinates validation, adapter execution, failure artifacts, JSON output, and quality gates. App-specific clients, prompts, parsers, workflow helpers, and secrets belong in adapters or the target app repo.
- `src/glasskit/eval/review/` owns the local review API, lossless point transport, deterministic range reconstruction, atomic YAML writes, byte-range video responses, and packaged static application. The contributor frontend lives in `review-ui/`; its Vite build output is committed under `src/glasskit/eval/review/static/` so installed packages do not need Node.js.
- `README.md` is user-facing. Keep it detailed and friendly. This file is for developers changing CLI internals, tests, packaging, or the adapter contract.
- Default pytest must stay offline. Use synthetic videos and fake adapters for tests. Committed video fixtures live under `tests/fixtures/videos/`; keep them reproducible with `tests/fixtures/generate-videos.sh`. Ordinary pytest runs should not require a system `ffmpeg` executable. If a video edge case needs default coverage, add a committed synthetic fixture for it.

## Key Files

- `pyproject.toml`: package metadata, `glasskit = "glasskit.cli:app"` console entry point, runtime dependencies, and dev tools.
- `src/glasskit/cli.py`: Typer command definitions and CLI exit-code handling.
- `src/glasskit/eval/models.py`: dataclasses, protocols, JSON value aliases, result types, and eval errors.
- `src/glasskit/eval/expectations.py` and `src/glasskit/eval/schemas.py`: eval directory discovery, YAML parsing, timestamp expansion, target config merging, and thresholds.
- `src/glasskit/eval/runner.py`: validation and run orchestration, adapter lifecycle, reports, artifacts, and quality gates.
- `src/glasskit/eval/adapters.py`: adapter target loading and normalization for simple functions, factories, and evaluator objects.
- `src/glasskit/eval/video.py`, `compare.py`, and `report.py`: frame decoding, comparison modes, and Rich output.
- `src/glasskit/eval/review/`: review document models, YAML reconstruction, local HTTP server, and generated static assets.
- `review-ui/`: React, TypeScript, Vite, Vitest, and Oxlint contributor workspace for the review application.
- `tests/eval/`: focused unit and integration tests using fake adapters and committed fixtures.
- `tests/fixtures/`: reproducible videos and sample eval directories used by default tests.
- `PUBLISHING.md`: release runbook for the `glasskit.ai` PyPI package and tag-triggered Trusted Publishing flow.
- `../.github/workflows/ci.yml` and `../.github/workflows/release.yml`: repository-level CI and PyPI release automation for this package. Keep their package commands scoped to the `cli/` working directory.

## Commands

- `uv run ty check && uv run pytest && uv run ruff check --fix && uv run ruff format`: run after code changes.
- `cd review-ui && npm ci && npm run check && npm run build`: install, check, test, and rebuild the committed review UI assets after frontend changes.
- `uv run glasskit --help` and `uv run glasskit eval --help`: smoke-check the console entry point.
- `uv run glasskit eval review --eval-dir tests/fixtures/eval_suites/review`: launch the packaged review UI against the committed synthetic fixture.
- `uv run glasskit eval review --eval-dir tests/fixtures/eval_suites/review --port 8765 --no-open`, followed by `cd review-ui && GLASSKIT_REVIEW_BACKEND=http://127.0.0.1:8765 npm run dev` in another shell: run the frontend development server against the Python backend.
- For local testing against the Origami backend, run the CLI from the app backend directory so local adapter imports resolve naturally: `cd REPO-ROOT/examples/origami/backend && uv run --with-editable ../../../cli --env-file .env glasskit eval run --adapter eval_adapter.py:create_evaluator --eval-dir ../../../tmp/origami-full-run-eval-suite`

## Notes
- Commit messages for changes under this directory should start with `cli: `.
