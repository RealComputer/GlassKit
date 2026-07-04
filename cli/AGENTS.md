# GlassKit CLI Development

This package provides the `glasskit` command. Its current command group is recorded-video evaluation through `glasskit eval`.

GlassKit CLI turns recorded smart-glasses workflows into repeatable eval suites by sampling labeled video moments, calling an app-provided adapter, comparing JSON-like observations, and reporting quality gates for local and CI runs.

## Architecture

- `src/glasskit_ai/cli.py` wires the Typer app and exposes `glasskit eval run`, `validate`, `list-samples`, and `init-case`.
- The eval pipeline is app-agnostic. `expectations.py` discovers suites and cases, loads `suite.yaml`, expands `expected.yaml` sample blocks, and resolves case videos. `schemas.py` owns Pydantic validation for YAML shape. `video.py` probes and decodes requested frames with PyAV. `adapters.py` imports adapter targets from `module:callable` or `file.py:callable` and normalizes function or object evaluators. `compare.py` evaluates JSON-like observations, and `runner.py` coordinates validation, adapter execution, failure artifacts, JSON output, and quality gates. App-specific clients, prompts, parsers, workflow helpers, and secrets belong in adapters or the target app repo.
- `README.md` is user-facing. Keep it detailed and friendly, with examples written as if users are running from their own app repo using commands like `uv run --with glasskit.ai glasskit eval ...`. This file is for developers changing CLI internals, tests, packaging, or the adapter contract.
- Default pytest must stay offline. Use synthetic videos and fake adapters for tests. Committed video fixtures live under `tests/fixtures/videos/`; keep them reproducible with `tests/fixtures/generate-videos.sh`. Ordinary pytest runs should not require a system `ffmpeg` executable. If a video edge case needs default coverage, add a committed synthetic fixture for it.

## Key Files

- `pyproject.toml`: package metadata, `glasskit = "glasskit_ai.cli:app"` console entry point, runtime dependencies, and dev tools.
- `src/glasskit_ai/cli.py`: Typer command definitions and CLI exit-code handling.
- `src/glasskit_ai/eval/models.py`: dataclasses, protocols, JSON value aliases, result types, and eval errors.
- `src/glasskit_ai/eval/expectations.py` and `src/glasskit_ai/eval/schemas.py`: suite discovery, YAML parsing, timestamp expansion, target config merging, and thresholds.
- `src/glasskit_ai/eval/runner.py`: validation and run orchestration, adapter lifecycle, reports, artifacts, and quality gates.
- `src/glasskit_ai/eval/adapters.py`: adapter target loading and normalization for simple functions, factories, and evaluator objects.
- `src/glasskit_ai/eval/video.py`, `compare.py`, `report.py`, and `init_case.py`: frame decoding, comparison modes, Rich output, and starter case creation.
- `tests/eval/`: focused unit and integration tests using fake adapters and committed fixtures.
- `tests/fixtures/`: reproducible videos and sample eval suites used by default tests.

## Commands

- `uv run ty check && uv run pytest && uv run ruff check --fix && uv run ruff format`: run after changes.
- `uv run glasskit --help` and `uv run glasskit eval --help`: smoke-check the console entry point.
- For local testing against the Origami backend, run the CLI from the app backend directory so local adapter imports resolve naturally: `cd REPO-ROOT/examples/origami/backend && uv run --with-editable ../../../cli --env-file .env glasskit eval run --adapter eval_adapter.py:create_evaluator --suite eval-suite`
