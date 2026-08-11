# GlassKit Eval Review UI Development

This workspace contains the React application served by `glasskit eval review`. It is a focused editor for checking video frames against timed expectations and updating the case file without requiring users to understand its `at` and `range` source syntax.

## Features

- Browse cases and targets, filter both lists, and open the case file or eval config file source.
- Seek and play the case video, replace paused browser previews with the exact lossless frame used by eval execution, follow the most recently crossed sample for the selected target, change playback rate, enter or nudge the current time, navigate samples, add a sample, and download the exact eval frame.
- Inspect and scrub all targets on a zoomable timeline, or limit the view to the selected target. Equal typed expectation values receive the same color.
- Switch between the timeline and a table that groups consecutive equivalent samples for the selected target.
- Distinguish omitted draft expectations, intentionally unlabeled ignored samples, and explicit `null`; edit sample timing, expectations, comparison settings, notes, and ignore status; or delete samples when valid.
- Repair eligible sample issues, autosave valid changes, surface errors, and protect or discard unsaved drafts.
- Use keyboard shortcuts for playback, sample navigation and creation, and time nudging.
- Deep-link to a case, target, and requested time.

## Architecture

- `src/App.tsx` composes the application shell and owns application-wide keyboard shortcut dispatch.
- `src/state/AppContext.tsx` owns document loading, per-case editing and save state, URL selection, and unsaved-change protection. `src/state/reducer.ts` contains state transitions, while `src/state/editing.ts` contains sample mutation rules.
- `src/api/types.ts` is the frontend model of the review protocol. `src/api/client.ts` is the only HTTP boundary and talks to the Python server under `/api`.
- `src/components/VideoPanel.tsx` owns native playback and the authoritative paused-frame overlay. `src/api/client.ts` fetches exact frames from the Python server, while helpers for precise browser seeking and frame downloads live under `src/video/`.
- `src/components/ReviewViews.tsx` switches between the timeline and sample table. Timeline rendering, geometry, and expectation colors live in `src/components/Timeline.tsx` and `src/timeline/`.
- `src/components/SamplesTable.tsx` renders groups produced by `src/samples/grouping.ts`. `src/components/Inspector.tsx` manages validated sample drafts.
- `src/components/Overlays.tsx` contains drawers, dialogs, and toasts. `src/utils/shortcuts.ts` centralizes shortcut eligibility.
- `src/App.css` contains application layout and component styling; `src/index.css` contains the base theme and global styles.
- `vite.config.ts` configures React compilation, the development API proxy, and production output for Python packaging.
- Tests live beside the code they cover. Shared DOM setup and fixtures live under `src/test/`.

## Invariants

- Treat expanded samples as the user-facing model. `at` versus `range`, `origin`, and `display_groups` are persistence details owned by the Python backend and must not create different timeline or table behavior.
- Native video is only a smooth playback surface. Every paused playhead, including a selected or explicitly sought sample, must be covered by the lossless authoritative frame returned by the Python server's shared eval selector; downloads must use those same bytes. Never present a paused browser-decoded frame as the eval frame.

## Commands

- Run `npm install` first in a clean checkout or after dependency changes.
- Run `npm run fix && npm run check` after frontend changes.
- Run `npm run build` to verify the production bundle and refresh the ignored static output under `../src/glasskit/eval/review/static/`.
- For development, start the Python server from the CLI directory with `uv run glasskit eval review --eval-dir tests/fixtures/eval_directories/review --port 8765 --no-open`, then run `GLASSKIT_REVIEW_BACKEND=http://127.0.0.1:8765 npm run dev` here.
