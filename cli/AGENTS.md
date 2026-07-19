# GlassKit Eval CLI Development

This package currently provides GlassKit Eval through the `glasskit eval` command group.

GlassKit Eval turns recorded smart-glasses workflows into repeatable evals by sampling labeled video moments, calling an app-provided adapter, comparing JSON-like observations, reporting quality gates for local and CI runs, and reviewing timed expectations in a local browser UI.

## Architecture

- `src/glasskit/cli.py` wires the Typer app and exposes `glasskit eval run`, `validate`, `list-samples`, and `review`.
- The eval pipeline is app-agnostic. `expectations.py` discovers eval directories and case files, loads the eval config file, expands and filters case sample blocks, and resolves case videos. `schemas.py` owns Pydantic validation for YAML shape. `video.py` probes videos and streams requested frames from a single PyAV decoder per case and trial. `adapters.py` imports Python adapter targets from `module:callable` or `file.py:callable`, distinguishes individual `evaluate` adapters from native `evaluate_many` batch adapters, and normalizes sync and async calls. `process_adapters.py` launches language-neutral adapter commands, transports versioned NDJSON over standard streams, sends lossless PNG samples, multiplexes individual requests, captures process failures, and normalizes the process lifecycle to the same evaluator interface. `compare.py` evaluates JSON-like observations, and `runner.py` coordinates validation, sequential isolated trials, on-demand frame consumption, bounded per-target concurrency, adapter execution, cross-trial stability, failure artifacts, deterministic JSON output, and quality gates. App-specific clients, prompts, parsers, workflow helpers, and secrets belong in adapters or the target app repo.
- `src/glasskit/eval/review/` owns the local review API, lossless sample transport, deterministic range reconstruction, atomic YAML writes, byte-range video responses, and packaged static application. The contributor frontend lives in `review-ui/`; `hatch_build.py` builds its ignored Vite output and embeds it in wheel and sdist artifacts so installed packages do not need Node.js.
- `README.md` and `JSON_OUTPUT.md` are user-facing. Keep them detailed and friendly. This file is for developers changing CLI internals, tests, packaging, or the adapter contract.
- Default pytest must stay offline. Use synthetic videos and fake adapters for tests. Command-adapter transport tests use the standard-library fixture under `tests/fixtures/adapters/` so ordinary Python test runs do not require Node.js or another external adapter runtime. Committed video fixtures live under `tests/fixtures/videos/`; keep them reproducible with `tests/fixtures/generate-videos.sh`. Ordinary pytest runs should not require a system `ffmpeg` executable. If a video edge case needs default coverage, add a committed synthetic fixture for it.

## Key Files

- `pyproject.toml` and `hatch_build.py`: package metadata, `glasskit = "glasskit.cli:app"` console entry point, runtime dependencies, dev tools, and the frontend distribution build hook.
- `src/glasskit/cli.py`: Typer command definitions and CLI exit-code handling.
- `src/glasskit/eval/models.py`: dataclasses, protocols, JSON value aliases, result types, and eval errors.
- `src/glasskit/eval/expectations.py` and `src/glasskit/eval/schemas.py`: eval directory discovery, YAML parsing, timestamp expansion, target config merging, and thresholds.
- `src/glasskit/eval/runner.py`: validation and repeated-trial orchestration, fresh per-trial adapter lifecycles, on-demand frame cursor consumption, bounded individual-sample concurrency, target-bounded native batch dispatch, adapter timing, sample stability aggregation, reports, trial-scoped artifacts, and quality gates.
- `src/glasskit/eval/adapters.py`: adapter target loading, individual-versus-batch strategy detection, and sync/async normalization for simple functions, factories, and evaluator objects.
- `src/glasskit/eval/process_adapters.py`: command parsing, process startup and teardown, NDJSON protocol transport, PNG sample serialization, request multiplexing and cancellation, stderr diagnostics, and command-adapter capability negotiation.
- `src/glasskit/eval/video.py`, `compare.py`, and `report.py`: frame decoding, comparison modes, and Rich output.
- `src/glasskit/eval/review/`: review document models, YAML reconstruction, local HTTP server, and the ignored generated-static destination.
- `review-ui/`: React, TypeScript, Vite, and Vitest contributor workspace for the review application. See [`review-ui/AGENTS.md`](review-ui/AGENTS.md) for its features, architecture, and frontend-specific invariants.
- `tests/eval/`: focused unit and integration tests using fake adapters and committed fixtures.
- `tests/fixtures/`: reproducible videos and sample eval directories used by default tests.
- `JSON_OUTPUT.md`: machine-readable eval report format, repeated-run example, and result-structure semantics.
- `PUBLISHING.md`: release runbook for the `glasskit.ai` PyPI package and tag-triggered Trusted Publishing flow.
- `../.github/workflows/cli-ci.yml` and `../.github/workflows/release.yml`: repository-level CI and PyPI release automation for this package. Keep their package commands scoped to the `cli/` working directory.

## Commands

- `uv run ty check && uv run pytest && uv run ruff check --fix && uv run ruff format`: run after Python, packaging, or backend test-fixture changes.
- `cd review-ui && npm run fix && npm run check`: run after review UI changes. Run `npm install` first in a clean checkout or after dependency changes. `uv build --no-sources --clear` rebuilds and embeds its production assets automatically.
- `uv run glasskit --help` and `uv run glasskit eval --help`: smoke-check the console entry point.
- `uv build --no-sources --clear`, followed by `uv run glasskit eval review --eval-dir tests/fixtures/eval_directories/review`: build and launch the packaged review UI against the committed synthetic fixture.
- In a clean source checkout, run `(cd review-ui && npm install && npm run build)` once to generate the ignored static bundle before starting the Python backend with `uv run glasskit eval review --eval-dir tests/fixtures/eval_directories/review --port 8765 --no-open`. Then run `cd review-ui && GLASSKIT_REVIEW_BACKEND=http://127.0.0.1:8765 npm run dev` in another shell to use the frontend development server.
- For local testing against the Origami backend, run the CLI from the app backend directory so local adapter imports resolve naturally: `cd REPO-ROOT/examples/origami/backend && uv run --with-editable ../../../cli --env-file .env glasskit eval run --concurrency 2`.

## Notes
- Commit messages for changes under this directory should start with `cli: `.
