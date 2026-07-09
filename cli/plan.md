# Eval Review UI Plan

This document specifies a local browser UI for reviewing and fixing `glasskit eval` case YAML files against their source videos. The command should be `glasskit eval review --eval-dir eval`, bind to `127.0.0.1` by default, serve a React/Vite-built static frontend from the Python package, and provide a small local API for reading videos, expanding samples, validating edits, and writing reconstructed YAML back to disk.

## Recommended Direction

Build a case-first review tool. The user opens one case at a time, sees the case video, selects or focuses targets, reviews sample timestamps on a timeline, and edits timed expectations directly from the UI. The UI treats ranges as a convenience representation for consecutive point samples: the editing model is point-based, while the save model reconstructs compact YAML using ranges when adjacent samples have the same value and regular spacing.

Use HTML5 video playback for v1. Browser video gives native playback controls, fast seeking, simple packaging, and good enough review ergonomics for most timestamp/expectation fixes. It is not guaranteed to be frame-exact across codecs and browsers, while PyAV-based frame-accurate preview would match eval decoding more exactly but adds backend decode latency, cache design, image transport, and a less natural playback experience. The v1 UI should clearly show the numeric sample timestamp, provide small timestamp nudges, and leave a later extension point for a PyAV-backed exact-frame preview endpoint when users prove they need it.

Use a Vite + React + TypeScript frontend for the interactive UI, but ship only built static files in the Python package. Runtime users should not need Node. During development, contributors can run the Vite dev server against the local Python API, and release builds should include the compiled assets.

Use Python's `http.server.ThreadingHTTPServer` with a custom handler for v1 unless the implementation becomes awkward. The API surface is small, local-only, and package dependency weight matters for a CLI tool. The one nontrivial requirement is HTTP Range support for video seeking, so the server should implement Range responses deliberately for the case video endpoint. If routing, streaming, or development ergonomics become a real cost, revisit adding Starlette/Uvicorn as runtime dependencies.

## Product Scope

The v1 command is for manual review and YAML repair only. It does not run adapters, compare observations, display pass/fail results, or replace `glasskit eval run`. Users can still use eval output to identify failed timestamps, then open the same case in the review UI and fix expectations or timestamps.

The v1 UI supports selecting a case, selecting or focusing a target, playing and seeking the case video, seeing all expanded samples, creating sample points, editing sample timestamps and expected values, editing optional sample `field` and `compare` settings, editing optional sample comments, editing group/range boundaries through the point model, and deleting samples. Target IDs, labels, target config, workflow metadata, case thresholds, and video path should be visible but read-only.

The UI should autosave edits. Autosave should be optimistic but validated by the backend, with a visible saved/saving/error state. There is no backup-file workflow and no conflict resolution for external edits; the latest UI save can overwrite the case YAML because git is the expected history mechanism.

The UI should prevent invalid YAML and invalid eval state. Frontend controls should avoid impossible values, and the backend must reconstruct the case, validate it with the existing schema and overlap rules, reject invalid edits, and only write when the resulting case loads successfully.

## UI Spec

The layout should be simple, clean, and dense enough for repeated developer use. Use a left sidebar for cases and targets, a central video region, a timeline under the video, and a right inspector/table for selected sample details and read-only YAML context.

The left sidebar shows the eval directory, case list, selected case metadata, and a target list. The target list should include target ID, label when present, and sample count. Selecting a target puts the UI in target focus mode, but the timeline can still show faint context markers from other targets.

The central video region uses a native `<video>` element with custom adjacent controls for current time, duration, previous/next sample, play/pause, small time nudges, and playback rate if cheap to add. Clicking any sample seeks the video to that sample's timestamp. The current video time should drive a playhead line on the timeline.

The timeline should be a horizontal time scale with the selected target as the primary lane. Samples appear as ticks or compact chips positioned by timestamp. Consecutive samples with the same expectation, `field`, `compare`, and regular spacing appear as a translucent grouped band behind the individual ticks; call these groups "ranges" in the UI because that matches the YAML term. Other targets can appear as secondary lanes or subdued stacked markers below the selected target, with an "All targets" view available when the user wants cross-target context. When multiple samples share or nearly share the same timestamp, stack their markers downward within the lane so they do not overlap.

The right panel has two modes: a sample table and an inspector. The sample table lists the focused target's point samples with time, expectation summary, field, compare mode, comment indicator, and source group. The inspector edits the selected sample using type-aware controls: boolean toggle, number input, string input, null selector, and a JSON editor textarea for arrays/objects. It also provides controls for timestamp, comment, field, compare mode, and tolerance. For values that are hard to represent safely with simple controls, allow raw JSON editing with validation feedback.

Read-only YAML context should be visible somewhere without crowding the main workflow. A collapsible "Case YAML" or "Target Details" panel can show video path, description, sampling defaults, workflow target metadata, target config, thresholds, and the canonical reconstructed sample blocks for the selected target.

Keyboard shortcuts should be discoverable in the UI rather than memorized from documentation. Provide visible button labels or tooltips for play/pause, previous/next sample, nudge backward/forward, and create sample at current video time. Recommended defaults are Space for play/pause when not typing, `[` and `]` for previous/next sample, Left/Right for small nudges when the timeline is focused, Shift+Left/Right for larger nudges, and `A` for add sample at current time when not typing.

## YAML Model

The editing model is a normalized point list per target. Each point has `timestamp_s`, `expect`, optional `field`, optional `compare`, optional `comment`, and stable UI-only identity. Ranges from YAML are expanded to points using the existing eval expansion logic, but the UI does not require users to edit original source blocks directly.

Saving reconstructs YAML target samples from the normalized point list. Sort points by timestamp. Group adjacent points only when `expect`, `field`, `compare`, `comment`, and spacing are equal within a small epsilon. A group with two or more regularly spaced points writes as `range: [start, end]`, where `end` is `last_timestamp + every_s` because eval ranges are half-open. Include `every_s` when the group spacing differs from the case default. Single points write as `at: timestamp`. Noncontiguous points with the same value can remain separate `at` blocks; compacting them into `at: [...]` can be added later if it proves useful.

Add an optional `comment` field to sample blocks. This is not a YAML syntax comment; it is explicit eval data that survives parse/write cycles. Comments are visible and editable in the UI. Comments are not passed to adapters in v1 unless the existing sample model is deliberately extended later.

The writer may canonicalize case YAML and does not need to preserve original comments, quotes, key ordering beyond the canonical order, or hand formatting. Canonical top-level order should be `video`, `description`, `sampling`, `workflow`, `targets`, `thresholds` when fields are present. Target order should preserve the existing target order. Read-only target config and workflow metadata should be preserved exactly as loaded by YAML, subject to normal PyYAML serialization.

The backend should write atomically: render YAML to a temp file in the same directory, validate by loading the rendered case through the existing eval suite path, then replace the original file. If validation fails, keep the original file unchanged and return a structured error to the UI.

## API Spec

`GET /` serves the static frontend. Static asset paths should be cacheable for the life of the process, but API responses should not be cached.

`GET /api/suite` returns the resolved eval directory, cases, case validation summaries, and enough metadata to populate the sidebar. This endpoint should not decode videos.

`GET /api/cases/{case_name}` returns one case document with raw read-only metadata, resolved video path, video probe metadata, targets, normalized point samples, reconstructed groups, and validation warnings. The returned point list should include stable IDs derived from target ID, timestamp, and an ordinal, but the server should not rely on IDs as persistent YAML identifiers.

`GET /api/cases/{case_name}/video` streams the resolved video with HTTP Range support and a safe content type. The handler must ensure the requested case video path comes from the loaded case, not from arbitrary user input.

`PUT /api/cases/{case_name}/targets/{target_id}/samples` replaces the normalized point list for one target, reconstructs the case YAML, validates it, writes it atomically, and returns the updated case document. Replacing a target's sample list is simpler and safer than patching individual YAML blocks because the UI editing model is point-based.

`POST /api/cases/{case_name}/validate` can validate the current on-disk case and return errors without writing. This is useful for a refresh button or startup diagnostics.

Optional later endpoints include `GET /api/cases/{case_name}/frame?time=...` for PyAV-backed exact-frame preview, `PUT /api/cases/{case_name}/settings` for editable sampling defaults, and `POST /api/cases/{case_name}/targets/{target_id}/normalize` for explicit YAML compaction without changing values.

## Backend Implementation Plan

Add a Typer command `glasskit eval review` in `src/glasskit/cli.py`. Options should include `--eval-dir`, `--case`, `--host` defaulting to `127.0.0.1`, `--port` defaulting to `0` for an available port, `--no-open` to avoid launching a browser, and `--allow-empty` if needed for new eval construction. The command should start the local server, print the URL, optionally open the browser, and run until interrupted.

Create `src/glasskit/eval/review/` for review-specific backend code. Suggested modules are `server.py` for HTTP serving and routing, `documents.py` for loading cases into review documents, `writer.py` for point-list-to-YAML reconstruction and atomic writes, and `types.py` for Pydantic request/response models if helpful.

Reuse `load_eval_suite`, schema validation, video probing, and sample expansion where possible. Add source metadata needed by the UI without changing runner behavior broadly. If existing dataclasses do not carry enough information, keep review-only block metadata in the review document builder rather than widening core runner models prematurely.

Add optional `comment` to `RawSampleBlock` in `schemas.py`. Decide whether to add `comment` to `SampleExpectation`; if comments are only for review, the review loader can read raw YAML directly and avoid passing comments to adapters. The important part is that normal eval validation accepts sample comments so the UI can write them.

Implement canonical YAML rendering with `yaml.safe_dump(sort_keys=False, allow_unicode=True)`, after constructing ordered plain dictionaries. Keep emitted prose and scalar values readable, but do not spend v1 effort preserving stylistic details from the original YAML.

Implement local-only safety checks. The server should bind to localhost by default, reject path traversal, serve only package static files and videos referenced by loaded cases, and avoid exposing arbitrary filesystem reads.

## Frontend Implementation Plan

Create a frontend workspace such as `review-ui/` or `src/glasskit/eval/review/ui/` with Vite, React, TypeScript, and plain CSS or CSS modules. Keep the visual system restrained: neutral surfaces, clear table rows, strong focus states, compact controls, and no marketing-style hero layout.

Build API client types matching backend responses. The main state model should be selected case, selected target, video playback state, normalized samples by target, pending save state, and selected sample ID.

Build the read-only shell first: sidebar, video playback, target list, timeline with expanded samples, sample table, and inspector showing selected values. Verify that clicking samples seeks video and that current playback time moves the playhead.

Add editing next: create sample at current video time, delete selected sample, edit timestamp, edit expectation, edit field, edit compare settings, edit comment, and autosave target sample list. Use debouncing for text-heavy fields and immediate saves for discrete controls. Keep save operations serialized per target so rapid edits cannot reorder writes.

Add validation feedback. Invalid local input should show inline errors and avoid sending saves. Backend validation failures should restore or keep the last accepted server state and show the error in the save status area.

Add keyboard shortcuts only after the visible controls exist. The shortcut handler must ignore events while typing in inputs or textareas.

## Tests And Verification

Add backend unit tests for normalized point loading from `at` and `range` blocks, range reconstruction, singleton reconstruction, grouping boundaries when expectation or compare settings change, comment support, overlap rejection, invalid timestamp rejection, and preservation of read-only case sections.

Add server tests using stdlib HTTP clients or Typer command-level tests for suite loading, case document JSON, target sample replacement, validation failure behavior, and video Range responses. These tests should use committed synthetic fixtures and remain offline.

Add lightweight frontend tests only where they add value. The most important frontend risk is timeline/sample editing behavior, so unit-test pure grouping, formatting, and keyboard-selection helpers if the UI code becomes complex. Full browser automation can be optional unless the project adopts Playwright or Vitest as part of the frontend workflow.

Manual verification for the first implementation should include `uv run ty check`, `uv run pytest`, `uv run ruff check --fix`, `uv run ruff format`, `uv run glasskit eval review --eval-dir tests/fixtures/eval_suites/two-state --no-open`, browser review of the fixture video, creating/editing/deleting a sample, confirming YAML changes, and running `uv run glasskit eval validate --eval-dir tests/fixtures/eval_suites/two-state` against a copied fixture.

## Packaging And Documentation

Update `pyproject.toml` package data settings so built review UI assets are included in the wheel and source distribution. Keep Node and frontend build dependencies out of Python runtime dependencies.

Add package scripts or documented commands for frontend development and release builds. A release checklist should include building the frontend before Python packaging, or CI should enforce that built assets are current.

Update `README.md` with `glasskit eval review` usage, UI workflow, autosave behavior, local-only server notes, sample comment syntax, and the browser-seeking frame accuracy caveat. Update `AGENTS.md` if the frontend build/test commands become part of the normal development workflow.

## Phased Delivery

Phase 1 is backend document and writer support. Implement normalized point documents, `comment` schema support, YAML reconstruction, validation, and tests without a browser UI.

Phase 2 is the local review server and CLI command. Serve static placeholder UI, suite/case JSON, video Range responses, and target sample replacement. Add server tests.

Phase 3 is read-only React UI. Build the case/target navigator, video playback, timeline, sample table, inspector, and keyboard-visible controls without editing.

Phase 4 is editing and autosave. Add create, update, delete, type-aware expectation editors, target-level save calls, validation feedback, and canonical YAML writeback.

Phase 5 is timeline polish. Add grouped range bands, multi-target context lanes, stacked same-time markers, better zoom/pan for long videos, and shortcut refinements.

Phase 6 is packaging, docs, and release readiness. Include built assets, document development commands, update README and AGENTS, and verify package installation from a built wheel.

## Out Of Scope For V1

Running adapters from the UI, showing observed values, importing eval result JSON, editing target metadata/config/workflow sections, preserving YAML syntax comments or original formatting, multi-user or remote server use, backup/history management, and guaranteed frame-exact video review are out of scope for the first implementation.
