# GlassKit Eval Review UI Development

This workspace contains the React application served by `glasskit eval review`. It is a focused editor for checking video frames against timed expectations and updating the case file without requiring users to understand its `at` and `range` source syntax.

## Features

- Browse cases and targets, filter both lists, and open the case file or eval config file source.
- Seek and play the case video, navigate samples, nudge the current time, add a sample, and download the currently displayed frame as a PNG.
- Inspect all targets on a zoomable timeline. Every sample is a uniform tick; equal expectation values receive the same color, selection has a separate outline, and hover details show only the timestamp and expected value.
- Switch from the timeline to a table for the selected target.
- Edit a sample's timestamp, expectation type and value, field, comparison mode, tolerance, and comment in the inspector, or delete the sample when deletion is valid.
- Autosave valid edits to the case file, surface validation and persistence errors, guard unsaved work, and support reloading the accepted case file from disk.
- Use keyboard shortcuts for playback, repeated previous and next sample navigation, time nudging, and adding samples.

## Architecture

- `src/App.tsx` composes the header, case and target sidebar, video panel, review views, inspector, and overlays. It also owns application-wide keyboard shortcut dispatch.
- `src/state/AppContext.tsx` loads documents, coordinates case workspaces, exposes editing operations, debounces saves, serializes in-flight saves, updates the URL selection, and protects unsaved changes. `src/state/reducer.ts` contains the state transitions, and `src/state/editing.ts` contains sample-editing rules.
- `src/api/types.ts` is the frontend model of the review protocol. `src/api/client.ts` is the only HTTP boundary and talks to the Python server under `/api`.
- `src/components/VideoPanel.tsx` owns transport controls and the browser video element. `src/video/PreciseVideoSeeker.ts` coordinates frame seeking, while `src/video/downloadFrame.ts` captures the displayed native-resolution frame.
- `src/components/ReviewViews.tsx` owns the Timeline and Samples tabs and the shared toolbar. `src/components/Timeline.tsx` renders the ruler, lanes, sample ticks, playhead, tooltip, zoom, and scrubbing. Timeline geometry and expectation colors live under `src/timeline/`.
- `src/components/SamplesTable.tsx` renders source-agnostic consecutive groups produced by `src/samples/grouping.ts`. `src/components/Inspector.tsx` validates and edits the selected sample.
- `src/App.css` contains application layout and component styling; `src/index.css` contains the base theme and global styles.
- Tests live beside the code they cover. Shared DOM setup and fixtures live under `src/test/`.

## Notes

- Treat expanded samples as the user-facing model. `at` versus `range`, `origin`, and `display_groups` are persistence details owned by the Python backend and must not create different timeline or table behavior.
- Selecting or seeking a sample requests a precise preview, but browser decoding remains best effort and can show an adjacent encoded frame. (Depends on the browser impl.) Eval cli command use PyAV and their logic and may select different adjacent frame.

## Commands

- Run `npm run fix && npm run check` after frontend changes. `check` runs lint and formatting checks, TypeScript, and the Vitest suite.
- Run `npm run build` to verify the production bundle and refresh the ignored static output.
- For development, start the Python server from the CLI directory with `uv run glasskit eval review --eval-dir tests/fixtures/eval_directories/review --port 8765 --no-open`, then run `GLASSKIT_REVIEW_BACKEND=http://127.0.0.1:8765 npm run dev` here.
