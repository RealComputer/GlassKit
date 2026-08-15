# GlassKit Eval CLI Development

This package currently provides GlassKit Eval through the `glasskit eval` command group.

GlassKit Eval turns recorded smart-glasses workflows into repeatable evals by sampling labeled video moments, calling an app-provided adapter, comparing JSON-like observations, reporting quality gates for local and CI runs, and reviewing timed expectations in a local browser UI.

## Architecture

- The core data flow is `eval config and case files -> sampled video frames -> app adapter -> JSON-like observations -> comparisons and quality gates`.
- Python and process adapters share one evaluator boundary, keeping execution, concurrency, batching, validation, and cleanup app-agnostic.
- App-specific clients, prompts, parsers, workflow helpers, and secrets belong in adapters or the target app repository.
- Runs and seeds share the same adapter execution path. Runs isolate trials for stability analysis, while seeds turn observations into validated expectation edits.
- The review system pairs a local API with a packaged browser application, serves lossless paused previews through the same PyAV frame selector used by eval execution, represents omitted draft expectations distinctly from explicit `null`, and uses the same case model to reconstruct YAML edits deterministically.

## Key Files

- `pyproject.toml` and `hatch_build.py`: package metadata, `glasskit = "glasskit.cli:app"` console entry point, runtime dependencies, dev tools, and the frontend distribution build hook.
- `src/glasskit/cli.py`: Typer command definitions and CLI exit-code handling.
- `src/glasskit/eval/models.py`: dataclasses, protocols, JSON value aliases, result types, and eval errors.
- `src/glasskit/eval/expectations.py` and `src/glasskit/eval/schemas.py`: eval directory discovery, YAML parsing, local and cloud video reference resolution, timestamp expansion, case/target sample-default resolution, target config merging, and thresholds.
- `src/glasskit/eval/cloud_video.py`: S3-compatible uploads and authenticated downloads, public HTTP downloads, mandatory SHA-256 verification, content-addressed per-user caching, and cache pruning.
- `src/glasskit/eval/execution.py`: shared adapter construction and cleanup, on-demand frame cursor consumption, bounded individual-sample concurrency, target-bounded native batch dispatch, adapter timing, JSON observation validation, and cancellation draining.
- `src/glasskit/eval/checkpoints.py`: durable run and seed manifests, fsynced result journals, input fingerprints, resume validation, and checkpoint discovery.
- `src/glasskit/eval/seeding.py`: draft expectation selection, adapter-backed labeling, checkpoint recovery, field extraction, deterministic target reconstruction, candidate validation, concurrent-edit protection, and atomic complete-case updates.
- `src/glasskit/eval/runner.py`: validation and repeated-trial orchestration, fresh per-trial adapter lifecycles through the shared executor, checkpoint recovery, completion-time result callbacks, sample comparison, stability aggregation, reports, trial-scoped artifacts, and quality gates.
- `src/glasskit/eval/adapters.py`: adapter target loading, individual-versus-batch strategy detection, and sync/async normalization for simple functions, factories, and evaluator objects.
- `src/glasskit/eval/commands.py` and `process_adapters.py`: native direct-execution command parsing and serialization, shell-safe command display, process startup and teardown, NDJSON protocol transport, PNG sample serialization, request multiplexing and cancellation, stderr diagnostics, and command-adapter capability negotiation.
- `src/glasskit/eval/video.py`, `frame_export.py`, `compare.py`, and `report.py`: shared frame selection and display transforms, lossless CLI frame exports, comparison modes, Rich output, and transient interactive progress.
- `src/glasskit/eval/review/`: review document models, YAML reconstruction, local HTTP server with bounded authoritative-frame caching, and the ignored generated-static destination.
- `review-ui/`: React, TypeScript, Vite, and Vitest contributor workspace for the browser review application, labeled "Eval Editor" in its own UI. See [`review-ui/AGENTS.md`](review-ui/AGENTS.md) for its features, architecture, and frontend-specific invariants.
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

- `README.md` and `JSON_OUTPUT.md` are user-facing. Keep them friendly and useful, but include only content that helps users operate this tool. Do not expose internal implementation details there.
- Keep default pytest offline by using synthetic videos and fake adapters.
- Command-adapter transport tests use the standard-library fixture under `tests/fixtures/adapters/` so ordinary Python test runs do not require another adapter runtime.
- Keep committed video fixtures reproducible with `tests/fixtures/generate-videos.sh`. Ordinary pytest runs must not require a system `ffmpeg` executable.
- Add a committed synthetic fixture when a video edge case needs default test coverage.
- Commit messages for changes under this directory should start with `cli: `.
