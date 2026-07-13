# GlassKit Eval Review UI Development

This workspace contains the React application served by `glasskit eval review`. It is a focused editor for checking video frames against timed expectations and updating the case file without requiring users to understand its `at` and `range` source syntax.

## Features

- Browse cases and targets, filter both lists, and open the case file or eval config file source.
- Seek and play the case video, change playback rate, enter or nudge the current time, navigate samples, add a sample, and download the currently displayed native-resolution frame as a PNG.
- Inspect and scrub all targets on a zoomable timeline, or limit the view to the selected target. Every sample is a uniform tick; equal typed expectation values receive the same color, selection has a separate outline, and hover details show only the timestamp and expected value.
- Switch from the timeline to a table that groups consecutive samples with the same expectation, field, comparison settings, comment, and ignore reason for the selected target.
- Edit a sample's timestamp, expectation type and value, field, comparison mode, tolerance, comment, and ignore status in the inspector, including a required reason shown only for ignored samples, or delete the sample when deletion is valid.
- Repair eligible empty-target or out-of-bounds sample issues, autosave valid edits to the case file, surface validation and persistence errors, guard unsaved work, and support discarding drafts by reloading the accepted case file from disk.
- Use keyboard shortcuts for playback, repeated previous and next sample navigation, time nudging, and adding samples.
- Deep-link to the selected case, target, and requested time through the `case`, `target`, and `time` URL query parameters.

## Architecture

- `src/App.tsx` composes the header, case and target sidebar, video panel, review views, inspector, and overlays. It also owns application-wide keyboard shortcut dispatch.
- `src/state/AppContext.tsx` loads documents, coordinates per-case workspaces, exposes editing operations, debounces and serializes saves, merges responses with newer drafts, updates the URL selection, and protects unsaved changes. `src/state/reducer.ts` contains state transitions and repair-completeness rules, while `src/state/editing.ts` contains sample creation, duplicate detection, and deletion rules.
- `src/api/types.ts` is the frontend model of the review protocol. `src/api/client.ts` is the only HTTP boundary and talks to the Python server under `/api`.
- `src/components/VideoPanel.tsx` owns transport controls and the browser video element. `src/video/PreciseVideoSeeker.ts` coordinates cancellable seek generations and waits for frame presentation when the browser exposes `requestVideoFrameCallback`, while `src/video/downloadFrame.ts` captures the displayed native-resolution frame.
- `src/components/ReviewViews.tsx` owns the Timeline and Samples tabs and the shared toolbar. `src/components/Timeline.tsx` renders the ruler, lanes, sample ticks, playhead, tooltip, zoom, and scrubbing. Timeline geometry and expectation colors live under `src/timeline/`.
- `src/components/SamplesTable.tsx` renders source-agnostic consecutive groups produced by `src/samples/grouping.ts`. `src/components/Inspector.tsx` owns draft field state, validates edits, and reports form errors to the case workspace so invalid drafts cannot be saved or abandoned accidentally.
- `src/components/Overlays.tsx` renders the accepted-source drawer, keyboard-shortcut dialog, focus traps, and transient toasts. `src/utils/shortcuts.ts` decides when application shortcuts may handle an event.
- `src/App.css` contains application layout and component styling; `src/index.css` contains the base theme and global styles.
- `vite.config.ts` enables the React compiler, proxies `/api` to `GLASSKIT_REVIEW_BACKEND` during development, and writes production assets to `../src/glasskit/eval/review/static/` for Python packaging.
- Tests live beside the code they cover. Shared DOM setup and fixtures live under `src/test/`.

## Invariants

- Treat expanded samples as the user-facing model. `at` versus `range`, `origin`, and `display_groups` are persistence details owned by the Python backend and must not create different timeline or table behavior.
- Selecting or seeking a sample requests a precise browser preview, but media decoding is still browser-dependent and may present an adjacent encoded frame. Eval execution decodes with PyAV and can choose a different adjacent frame.

## Commands

- Run `npm install` first in a clean checkout or after dependency changes.
- Run `npm run fix && npm run check` after frontend changes.
- Run `npm run build` to verify the production bundle and refresh the ignored static output under `../src/glasskit/eval/review/static/`.
- For development, start the Python server from the CLI directory with `uv run glasskit eval review --eval-dir tests/fixtures/eval_directories/review --port 8765 --no-open`, then run `GLASSKIT_REVIEW_BACKEND=http://127.0.0.1:8765 npm run dev` here.
