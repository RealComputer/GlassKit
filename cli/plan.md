# GlassKit Eval Review UI Specification And Implementation Plan

## Document Status

This document is the implementation source of truth for the first complete version of the GlassKit eval review UI. It records the product decisions, user experience, data contracts, architecture, delivery sequence, and acceptance criteria needed to implement the feature without access to the design conversation that produced it.

The feature belongs to the existing `glasskit eval` command group and is launched with `glasskit eval review --eval-dir eval`. It is a local, desktop-oriented browser application for reviewing case YAML expectations against case videos and writing corrected timed expectations back to the YAML.

Items under "Deferred Work" are explicitly outside this version and should not be pulled into the initial implementation unless a concrete blocker is found.

## Problem

Reviewing a recorded-video eval currently requires opening the video in a media player, opening the case YAML in an editor, navigating both tools independently, translating timestamps manually, and repeatedly switching context. Confirming a single expectation is slow, and fixing an incorrect value or timestamp adds another error-prone editing step.

The review UI should put the video, sample schedule, expected values, and editing controls in one place. A user should be able to move directly from a failed timestamp reported by `glasskit eval run` to the relevant case and target, inspect the frame, correct the expectation or timestamp, and continue reviewing without manually editing YAML.

## Goals

- Make timed expectations fast to inspect against the source video.
- Make cases and targets easy to navigate even when a suite contains many of them.
- Show every expanded sample point on a shared, seekable video timeline.
- Support creating, editing, moving, and deleting sample points.
- Use type-aware controls for JSON-like expectations and comparison settings.
- Autosave valid edits to the case YAML without a separate save action.
- Reconstruct compact `range` blocks when point samples form a regular run.
- Keep all non-editable case and eval configuration visible and semantically unchanged.
- Ship the UI inside the Python package so an installed `glasskit` command has no Node.js runtime requirement.
- Keep the server local-only, dependency-light, offline-capable, and consistent with the current CLI architecture.

## Success Criteria

A user can launch the command, choose a case and target, click a sample to seek the video, determine whether its expectation is correct, change the expectation or timestamp, see a successful autosave state, and confirm that the case YAML now represents the same edited point schedule.

The installed wheel and source distribution contain everything needed to run the UI. Node.js is needed only by contributors who modify the frontend.

The regular eval commands continue to load and evaluate case files written by the UI. Existing cases are not changed merely by opening the UI; a case is rewritten only after an edit.

## Non-Goals

- Running adapters or evals from the UI.
- Showing observed values, pass/fail results, failure artifacts, or imported eval result JSON.
- Editing case metadata, target IDs, labels, target config, workflow metadata, sampling defaults, thresholds, the video path, or eval-level config.
- Creating or deleting cases or targets.
- Preserving YAML comments, anchors, quoting style, flow style, or hand formatting after a file is edited.
- Remote access, collaboration, authentication, or multi-user conflict resolution.
- Backups, an undo history, or source-control integration. Git is the expected history mechanism.
- Guaranteed frame-identical preview between the browser and PyAV.
- Transcoding videos that a browser cannot play.
- Mobile-first behavior.

## Existing CLI Context

GlassKit is a Python 3.12+ CLI distributed as the `glasskit.ai` package. The console entry point is `glasskit = "glasskit.cli:app"`. Typer commands are defined in `src/glasskit/cli.py`.

The current eval implementation is app-agnostic:

- `src/glasskit/eval/schemas.py` validates YAML with Pydantic. Unknown fields are rejected except extra metadata on `workflow.targets` entries.
- `src/glasskit/eval/expectations.py` discovers `config.yaml`, discovers `.yaml` and `.yml` case files under `cases/`, resolves video paths, merges workflow and target metadata, expands sample blocks, and rejects overlapping source intervals.
- `src/glasskit/eval/video.py` probes and decodes video with PyAV. Eval decoding selects the nearest decoded frame to each requested timestamp after normalizing the first decoded frame to time zero.
- `src/glasskit/eval/models.py` contains the internal dataclasses and JSON-like value aliases.
- `src/glasskit/eval/runner.py` validates video durations, calls adapters, compares observations, and reports results.

The review feature must reuse these rules instead of creating a second interpretation of case YAML.

### Eval Directory Shape

An eval directory normally has this shape:

```text
eval/
  config.yaml          # optional, read-only in the review UI
  adapter.py           # irrelevant to the review UI
  cases/
    case-001.yaml
    case-002.yml
```

Case names are filename stems. The existing loader rejects a suite when `.yaml` and `.yml` files share the same stem. A case's `video` path is resolved relative to the case YAML file, not the shell working directory.

### Existing Sample Semantics

A representative case is:

```yaml
video: "../../../recordings/task-01.mp4"
description: "Bracket installation"
sampling:
  every_s: 0.5
targets:
  bracket_seated:
    label: "Bracket seated"
    config:
      prompt_id: workflow.bracket_seated
    samples:
      - range: [0.0, 3.0]
        expect: false
      - at: [3.5, 4.0]
        field: result.matches
        expect: true
        compare:
          mode: exact
thresholds:
  min_pass_rate: 0.9
```

Each sample block has exactly one of `range` or `at`. `range: [start, end]` is half-open and expands at `every_s`, inherited from `sampling.every_s` when omitted. `at` may be one timestamp or a list. Timestamps are finite, nonnegative seconds and are rounded to nine decimal places by the current expansion code. The default `every_s` is `0.5`.

Within one target, source intervals may not overlap. This is stricter than merely rejecting duplicate expanded timestamps: a point inside a declared range is invalid even when it does not land on that range's cadence. The writer described below must account for this rule.

`expect` is a JSON-like value: `null`, a boolean, a finite number, a string, an array, or an object with string keys. `field` is an optional dot-separated extraction path. `compare` may contain a supported mode and a nonnegative numeric tolerance. When mode is omitted, booleans, strings, `null`, arrays, and objects use `exact`, while non-boolean numbers use `numeric`.

Supported explicit comparison modes are `exact`, `numeric`, `json_subset`, `set_equals`, `set_contains_any`, and `set_contains_all`.

Target sample lists are allowed by the Pydantic shape to be empty, but normal eval loading rejects empty targets unless `--allow-empty` is used. The review UI may load an empty target so the user can add its first sample, but it must not create a new empty target or let the user delete the final sample from a previously valid target.

## Decisions At A Glance

| Area | Decision |
| --- | --- |
| Entry point | `glasskit eval review --eval-dir eval` |
| Application model | Case-first, with one focused target and optional context lanes for all targets |
| Runtime | Local Python server plus a packaged static browser app |
| Backend server | `http.server.ThreadingHTTPServer` with a small explicit router |
| Bind address | Always `127.0.0.1` in this version |
| Frontend | Vite, React, TypeScript, plain CSS, and Lucide React icons |
| Frontend state | React context plus `useReducer`; no external state-management package |
| Video | Best-effort HTML5 `<video>` preview with HTTP byte-range support and presented-frame timestamp reporting |
| Timeline | DOM and CSS, one lane per target, derived range bands, and point markers |
| Editing model | Normalized point samples; ranges are derived display and storage groups |
| Saving | Validated autosave, serialized per case, with visible state |
| Write API | Replace all normalized points for one existing target |
| YAML formatting | Semantic preservation of read-only values; normal PyYAML formatting after an edit |
| History | No backup, confirmation dialog, or undo stack; rely on Git |
| Browser support | Current desktop Chromium, Firefox, and Safari where the source codec is natively playable |
| API style | Same-origin JSON under `/api`, snake_case field names, structured errors |
| Exact eval frames | Not included; the shipped UI does not guarantee browser/PyAV frame identity |

## User Experience

### Launch

The primary command is:

```bash
uv run glasskit eval review --eval-dir eval
```

The server binds to `127.0.0.1` on an available port, prints the exact URL, opens the default browser after the socket is listening, and continues until interrupted. `Ctrl+C` shuts it down cleanly and exits `0`. Invalid eval paths/selectors, missing packaged assets, and bind failures print a concise Rich error and exit `2`. Failure to open the browser is nonfatal: print the URL and continue serving.

The command also supports:

```text
--eval-dir PATH   Eval directory; default: eval
--case TEXT       Initially open this case by filename or stem
--target TEXT     Initially focus this target; requires --case
--port INTEGER    Local port; default: 0, meaning choose an available port
--no-open         Print the URL without opening a browser
```

`--case` and `--target` choose the initial UI selection; they do not hide other cases or targets. Invalid selectors are CLI errors before the browser opens. State this distinction in `--help`.

Transfer the initial selection in the opened URL as percent-encoded `case` and `target` query parameters. The frontend updates those parameters with `history.replaceState` when selection changes, so reload preserves context without adding a routing dependency.

There is no `--host` option because remote serving is outside the product scope. There is no `--allow-empty` option because review loading always tolerates existing empty sample lists for the purpose of adding the first point, while write validation still protects normal eval validity.

### Primary Workflow

1. Launch the review command, optionally selecting the failed case and target reported by a separate eval run.
2. Select a case from the left sidebar and a target from that case.
3. Play or seek the video. Click a point marker or table row to select the sample and seek to its timestamp.
4. Inspect the expected value and optional field, comparison, tolerance, and comment in the right inspector.
5. Edit a value, move the timestamp, create a point at the playhead, or delete a point.
6. See `Saving`, then `Saved` in the header. Continue to the previous or next point without a manual save action.
7. Use the source drawer when read-only YAML context is needed.

### Screen Layout

The default desktop layout uses three columns and a compact top bar:

```text
+----------------------------------------------------------------------------------+
| GlassKit Eval Review | case-001 | 00:03.500 / 00:18.200 | Saving/Saved/Error     |
+----------------------+----------------------------------------------+------------+
| Cases                | Video                                        | Inspector  |
| [filter...]          |                                              | Time       |
| > case-001           |                                              | Expect     |
|   case-002           | Native controls + review transport           | Field      |
|                      +----------------------------------------------+ Compare    |
| Targets              | Timeline toolbar: fit 2x 4x 8x, lanes toggle | Comment    |
| > bracket_seated     | Time axis                                    | Delete     |
|   step_complete      | bracket_seated  [band] | | |                 |            |
|                      | step_complete       |     [band] | |         |            |
| Case details         +----------------------------------------------+------------+
| Eval config          | Samples table: time | expectation | field | compare       |
+----------------------+-----------------------------------------------------------+
```

At widths of 1200 px and above, the left sidebar is 240 px, the inspector is 340 px, and the center takes the remaining width with a 600 px minimum. From 1024 px through 1199 px, use a two-column shell with a 220 px sidebar and put the inspector as a full-width section below the center table. Widths below 1024 px may scroll horizontally around a 1024 px minimum application width; mobile optimization is not required. Controls and text must never overlap.

The video itself is the primary visual asset and should remain prominent without using a decorative card. The overall visual style is a restrained developer tool: neutral surfaces, one clear selection accent, semantic save/error colors, compact typography, strong focus rings, square or lightly rounded controls, and no marketing decoration.

Use Lucide icons for familiar actions such as play, pause, skip, add, delete, zoom, refresh, and panel toggles. Icon-only controls need tooltips and accessible labels. Visible text should describe data and commands, not explain the product.

Use a light theme for the initial implementation with system sans-serif text, system monospace for times and YAML/JSON, a 14 px body size, a 4 px spacing base, borders rather than shadows for panel separation, and radii no larger than 6 px. Recommended starting tokens are `#f6f8fa` app background, `#ffffff` work surfaces, `#1f2328` primary text, `#59636e` secondary text, `#d0d7de` borders, `#0969da` selection/action, `#1a7f37` saved, `#9a6700` pending, and `#cf222e` error. Verify contrast rather than treating these literals as exempt from accessibility checks. Keep context lanes neutral and use the accent only for the focused lane and selected point; expectation truth values are data, not success/failure colors.

### Header

The header shows the product name, selected case, selected target when space permits, current video time and duration, and the global autosave state.

Save states are:

- `Saved`: no local changes are pending.
- `Saving`: a valid change is queued or in flight.
- `Unsaved`: local input is valid but waiting for the debounce timer.
- `Fix errors`: local form input is invalid and has not been sent.
- `Save failed`: the backend rejected or could not persist the change. The draft remains visible, with `Retry` and `Reload from disk` actions.

Do not show success toasts after every edit. The persistent header state is enough. Use a toast only for a meaningful automatic correction, such as resetting an incompatible comparison mode after the expectation type changes.

### Case And Target Sidebar

The case list is filename-sorted to match existing discovery. It has a text filter that matches case name and description. Each row shows the case name, total expanded point count, and an error indicator when the case cannot be reviewed.

Selecting a case loads its document and video metadata, chooses the first target unless an initial or remembered target is available, clears the old video source, and then loads the new source. The selected case remains obvious while scrolling.

The target list preserves YAML mapping order. It has a compact ID/label filter for suites with many targets. Each row shows label when present, target ID, and point count. The focused target controls the inspector, sample table, previous/next navigation, add action, and the emphasized timeline lane.

A case that cannot be parsed into normalized points remains visible with its error and source text, but its editor is disabled. A case with normalized points but repairable sample issues, specifically an empty target or a timestamp beyond the video duration, remains editable so the user can fix it; the backend accepts only a candidate that resolves all such issues. This prevents one broken case from hiding every other case while keeping structural YAML repair in a text editor.

The sidebar also contains collapsible read-only sections for case details and eval config. The complete current case source is available in a `Case YAML` drawer, and the complete `config.yaml` source is available when that file exists. This guarantees that all YAML values remain inspectable even when they do not have a dedicated control.

### Video And Transport

Use a native `<video controls preload="metadata">` element. Preserve the source aspect ratio and fit it within the available center area on a dark neutral background. Cap the video region at `44vh` and `520px` so the timeline remains visible on an ordinary laptop display; portrait video uses contained empty side space rather than cropping. Do not autoplay.

The review transport adjacent to the native controls provides:

- Previous sample in the focused target.
- Play or pause.
- Next sample in the focused target.
- Nudge playhead backward or forward by `0.1` seconds.
- Nudge playhead backward or forward by `1.0` second through the shifted shortcut.
- Current time input with millisecond display precision.
- Playback rate menu with `0.5x`, `1x`, `1.5x`, and `2x`.
- Add point at the current playhead time.

Seeking clamps to `[0, duration]`. Creating a point rounds the browser playhead to three decimal places; existing timestamps retain up to the current loader's nine-decimal precision unless edited. The UI displays three decimals by default and allows direct timestamp input with a `0.001` step.

Previous and next operate relative to the selected point when one exists, otherwise relative to the playhead. They do not wrap at the ends; the unavailable direction is disabled.

Clicking a point pauses playback and assigns its timestamp to `video.currentTime`; do not use `fastSeek()`. Increment a monotonically increasing seek generation and mark the preview as seeking until the current generation receives `seeked`. When `HTMLVideoElement.requestVideoFrameCallback()` is available, request a callback as part of the same seek cycle and prefer to keep the preview in the seeking state until a callback for the current generation supplies `metadata.mediaTime`. Ignore a callback observed before that generation's `seeked`, request another, and fall back to ready without a shown-frame value when no post-seek callback arrives within `500 ms` of `seeked`. Cancel prior callback handles and ignore every listener, callback, and timeout whose generation is stale.

The transport shows the authoritative eval sample time and, when available, the browser-presented frame PTS, for example `Sample 03.500s | Shown 03.467s`. The shown time is diagnostic only: do not rewrite the sample timestamp, perform a corrective second seek, or claim that the browser frame is the frame selected by PyAV. When `requestVideoFrameCallback()` is unavailable, complete the preview after `seeked` and omit the shown-frame value.

When the browser reports that the media cannot play, show the video path, container, and a clear browser-codec error. The user may still inspect source data, but editing is disabled when video duration cannot be established because timestamp bounds cannot be validated. Do not add transcoding in this version.

### Frame Accuracy Decision

The product decision is to ship a best-effort HTML video preview and accept that it is not frame-identical to eval decoding. HTML video provides smooth playback, native seeking, rate controls, low latency, and simple packaging. No PyAV still-image endpoint, WebCodecs decoder, browser-frame correction loop, or exact-frame mode is required by this implementation.

The eval decoder uses PyAV and chooses the nearest decoded frame after subtracting the first decoded frame timestamp. A browser uses its own media timeline and presentation policy. For ordinary well-timestamped video, the browser will commonly show the same or an adjacent frame: approximately `42 ms` at 24 fps, `33 ms` at 30 fps, or `17 ms` at 60 fps. Adjacent frames usually have the same workflow meaning, but a state transition, scene cut, brief occlusion, motion blur, rapidly changing text, variable frame rate, or unusual timestamp origin can make the difference visible or semantically important. This is an accepted limitation, not a correctness guarantee.

HTTP Range support and `currentTime` provide a precise media-time seek request; keyframe spacing may affect seek latency but should not be treated as permission to intentionally stop at a keyframe. `requestVideoFrameCallback()` improves readiness and observability by reporting the PTS actually presented, but it does not force browser/PyAV parity. The UI and README must use language such as "browser preview" or "shown frame," never "eval frame" or "exact frame."

Keep an exact PyAV still preview as deferred work only. Add it later if representative recordings demonstrate material expectation mistakes from adjacent-frame or timeline-origin differences; the present architecture does not need to implement speculative endpoint or caching code for it.

### Timeline

Use an accessible DOM/CSS timeline, not canvas. Each target has one horizontal lane, so samples from different targets at the same timestamp naturally stack downward without colliding. Duplicate timestamps inside one target are invalid and therefore do not require same-lane stacking.

The timeline has a sticky time ruler, a moving playhead, sticky target labels, one marker per normalized point, and translucent bands for point groups that the writer will serialize as ranges. A marker is a real button with an accessible label containing target, timestamp, and a compact expectation summary. The visible hit area must remain usable even when the marker line is narrow.

Default mode shows all target lanes in YAML order. The focused lane is taller and fully opaque; context lanes are compact and subdued. Cap the lanes viewport near 220 px and scroll it vertically while keeping the time ruler and target labels sticky. A `Selected only` toggle hides context lanes when a case has many targets. Clicking any context marker also focuses its target.

Clicking empty timeline space seeks the video without creating a sample. Point creation is intentional through the Add button or keyboard shortcut. Clicking a range band selects its first point; range bands are derived visualization, not editable objects.

Timeline zoom is required, not a deferred polish item. Provide `Fit`, `2x`, `4x`, and `8x` as a segmented control. `Fit` maps the full duration to the viewport. Higher levels multiply track width and enable horizontal scrolling. Changing zoom keeps the playhead or selected sample near the same viewport position. Seeking or selecting a sample scrolls it into view; ordinary playback should not continuously force-scroll a user who has manually moved elsewhere.

The frontend receives display groups from the backend, calculated by the same reconstruction logic used for YAML. This prevents the UI from showing a range band that the writer will not emit.

### Samples Table

The samples table sits below the timeline and shows every point for the focused target, sorted by timestamp. Columns are timestamp, compact expectation, field, effective comparison mode, tolerance, comment indicator, and source kind.

Selecting a row selects the marker, seeks and pauses the video, scrolls the marker into view, and populates the inspector. The table is read-only except through the inspector. Keep the header sticky and the body independently scrollable. A simple DOM table is adequate initially; add row virtualization only if profiling shows a real problem with large suites.

### Sample Inspector

The inspector edits exactly one normalized point. It contains:

- Timestamp input and small nudge buttons for `-0.1`, `+0.1`, `-1.0`, and `+1.0` seconds. Moving the sample also seeks the video.
- Expectation type selector: Null, Boolean, Number, String, Array, or Object.
- A type-specific expectation editor.
- Optional field input.
- Comparison mode menu with `Auto` plus supported explicit modes.
- Tolerance input when numeric comparison is applicable.
- Optional multiline comment.
- Read-only derived group information when the point belongs to a serialized range.
- Delete action, disabled when deletion would leave a previously valid target empty.

Boolean uses a toggle. Number uses a finite numeric input and must distinguish numbers from booleans. String uses a three-row textarea so long expected text remains editable without changing control type. Null has no value input. Arrays and objects use a plain JSON textarea with parse errors shown inline; do not add Monaco or another large editor dependency.

The mode menu should guide new edits without rejecting legacy files accepted by the existing schema:

- `Auto` and `exact` are available for every expectation type.
- `numeric` is offered for numbers.
- `json_subset` is offered for arrays and objects.
- Set modes are offered for arrays.
- Tolerance is enabled for a numeric expectation when mode is `Auto` or `numeric`.

If the user changes expectation type and the current explicit mode no longer makes sense, switch the mode to `Auto`, clear an inapplicable tolerance, and show one concise toast. Existing unusual mode/value combinations loaded from disk remain visible and can be preserved until the user changes them.

Blank field and comment inputs serialize as absent fields, not empty strings.

### Keyboard Shortcuts

Shortcuts are conveniences, not hidden requirements. Put the shortcut next to the relevant button in its tooltip or visible `kbd` label, and provide a small keyboard help popover.

| Shortcut | Action |
| --- | --- |
| `Space` | Play or pause |
| `[` | Select and seek to previous point in the focused target |
| `]` | Select and seek to next point in the focused target |
| `Left` | Nudge playhead backward `0.1` seconds |
| `Right` | Nudge playhead forward `0.1` seconds |
| `Shift+Left` | Nudge playhead backward `1.0` second |
| `Shift+Right` | Nudge playhead forward `1.0` second |
| `A` | Add a point at the playhead for the focused target |

Global handlers must ignore these shortcuts while the user is typing in an input, textarea, select, or content-editable element. Do not assign a destructive delete shortcut in this version.

### Loading, Empty, And Error States

Use skeletons or stable placeholders while case metadata loads so the layout does not jump. An empty target shows its video and an explicit `Add first sample` action. A suite with no discoverable cases is a CLI startup error because this UI does not create cases.

Local validation errors stay next to their field and block autosave. Backend errors appear both in the persistent save status and near the relevant control when a path is available. Network or disk failures retain the user's draft in memory.

Switching cases or reloading the page while a save is queued first flushes the latest valid draft. If the active control contains an invalid partial value, keep the user on the case and require them to fix or reset that field instead of silently discarding it. If a save fails, keep the user on the current case and offer `Retry` or `Reload from disk`. Install `beforeunload` only while a valid change is pending, invalid dirty input exists, or a failed draft is unsaved; normal saved use must not produce a leave-page warning.

## Editing Model

### Normalized Point

The browser and review backend work with expanded points rather than source sample blocks:

```json
{
  "id": "block-1-point-0",
  "timestamp_s": 1.5,
  "expect": true,
  "field": "result.matches",
  "compare": {
    "mode": null,
    "tolerance": null
  },
  "comment": "Bracket becomes clearly seated here.",
  "origin": {
    "block_index": 1,
    "kind": "range",
    "every_s": 0.5
  }
}
```

`id` is an opaque UI identity and is never written to YAML. Loaded IDs are deterministic within one document load, using source block and expanded point position. New points use `crypto.randomUUID()`. A successful PUT echoes request IDs so selection remains stable. Reloading from disk may assign different IDs.

`origin` is a read-only compaction hint. It records whether loaded points came from the same original block and its effective cadence. It is never eval data and is not written. The writer uses it only for the two-point range rule defined below. New points have `origin: null`. After a successful save, the server recomputes origin from the blocks it actually emitted while preserving point IDs; this keeps a newly emitted custom range stable during later edits in the same browser session.

`compare.mode: null` means automatic mode inference. `compare` is always an object over the wire, with nullable `mode` and `tolerance`; the writer omits YAML `compare` when both are null. Expected objects are compared structurally for grouping, with mapping key order ignored and JSON types respected.

`display_groups` describes the blocks produced by reconstruction and is server-owned:

```json
{
  "id": "group-0",
  "kind": "range",
  "point_ids": ["block-1-point-0", "block-1-point-1"],
  "start_s": 1.0,
  "end_s": 2.0,
  "every_s": 0.5,
  "timestamps_s": [1.0, 1.5]
}
```

Return one display group for every emitted `range` or `at` block, in block order. `start_s`, `end_s`, and `every_s` are non-null only for ranges; `timestamps_s` always lists the represented points. Group IDs are response-local and are not written. The timeline draws bands only for `kind: "range"`, while the inspector may show either kind.

### Create

Add creates a point at the current playhead rounded to three decimal places. If the focused target already has a point at that time within `1e-9`, select the existing point and do not create a duplicate.

The new point copies `expect`, `field`, and `compare` from the closest existing point in the focused target, preferring the earlier point on a tie. It does not copy the comment or origin. If the target has no points, default to `expect: false`, automatic comparison, no field, and no comment. Focus the expectation editor after creation.

### Edit

Timestamp edits clamp through controls but are rejected by the backend if negative, non-finite, duplicate within the target, or beyond video duration using the existing `validate_sample_times` tolerance. The inspector should prevent ordinary out-of-range input before a request is sent.

Expectation, field, compare, tolerance, and comment edits affect only the selected point. Editing one point from a derived range may split that range into smaller groups on the next save. This is expected and should update the bands after the server response.

There are no direct range start, range end, or cadence editors. A range is the derived compact representation of compatible points. Users change it by moving, adding, deleting, or editing points.

### Delete

Delete removes the selected point and autosaves immediately. There is no confirmation dialog or undo history. After deletion, select the next point by time, or the previous one when no next point exists.

Disable deletion when it would remove the final point from a nonempty target. Existing empty targets are allowed only as a repair state and can receive their first point.

## Autosave And Concurrency

The frontend keeps a draft point list for the focused case. Discrete operations such as toggles, create, delete, and mode selection enqueue a save immediately. Text, JSON, comment, and numeric typing save after `400 ms` of idle time or on blur, whichever comes first. Invalid partial input does not alter the last valid point model and does not call the API.

All writes are serialized per case, not per target. Two target-level writes based on the same case file can otherwise overwrite one another. The queue coalesces pending updates for the same target to the newest valid point list but never allows more than one write for a case in flight.

Assign a monotonically increasing local edit version to each target. A queued request records the sent target version. When its full-case response arrives, update accepted disk metadata and revision, but replace a target's local points only when that target has not changed since the request snapshot. In particular, a response for target A must never overwrite unsent edits to target B, and a response for an older version of target A must not replace its newer draft. The `source_yaml` drawer represents the last accepted on-disk source and may temporarily lag valid queued drafts.

The server also holds one lock per case path. Under the lock it rereads the latest file, replaces only the requested target's `samples`, validates the candidate, and atomically writes it. This preserves external edits to other case sections and prevents requests from different browser threads from losing changes.

External changes to the same target are intentionally last-writer-wins. There is no merge or conflict dialog. A revision hash returned by the API is informational and helps the UI detect that a refresh changed the file, but a mismatch does not reject a save. Multi-tab editing is unsupported.

On save failure, keep the valid local draft and stop dequeuing later case navigation. `Retry` resends the newest draft. `Reload from disk` explicitly discards it and fetches the current case.

## YAML Read And Write Contract

### Explicit Sample Comment

Add an optional `comment: str | None` field to `RawSampleBlock` in `schemas.py` and `SampleExpectation` in `models.py`. It is real YAML data, not a YAML syntax comment. Trim surrounding whitespace during validation, reject a present but blank YAML comment, and omit the key when the UI is blank. Preserve internal newlines for a multiline comment. A source range or `at` list gives its comment to every expanded point; points group back together only when comments match.

Comments do not affect adapter calls, comparisons, reports, or sample identity. The shared expectation model retains them solely so review loading does not need a parallel expansion path. Do not add them to adapter input or eval result output in this implementation. Update the public README sample-field reference as part of this feature.

### Loading Points

Review loading parses the raw mapping with the existing schema, resolves the video, and expands blocks with the same timestamp and overlap logic used by `load_eval_suite`. It additionally retains source block index, source kind, effective cadence, explicit compare settings, comment, and raw source text.

Refactor the existing private case-loading logic into reusable internal functions rather than copying expansion rules into the review package. Runner behavior and current error text should remain stable unless a test demonstrates that a deliberate change is needed.

The review suite index should discover files first and load each case independently. A malformed case becomes an error summary instead of aborting all valid cases. Duplicate case stems and invalid eval-level config remain suite-level startup errors because they make case identity or shared configuration ambiguous.

### Reconstruction Rules

The serializer receives the complete normalized point list for one target and produces that target's complete `samples` list. Its output must expand back to exactly the submitted timestamps and payloads under existing eval rules.

Define a point payload as `expect`, normalized `field`, explicit `compare` configuration, and normalized `comment`. Origin and UI ID are not payload.

Use this deterministic algorithm:

1. Validate every point and sort by `timestamp_s`, using ID only as a stable error-reporting tie breaker.
2. Reject timestamps that differ by at most `1e-9` within the target.
3. Partition the sorted list into maximal runs of adjacent points with structurally equal payloads. A point with a different payload always ends the run, even if the earlier payload appears again later.
4. Scan each payload run greedily from left to right. At the current point, use the gap to the next point as a candidate cadence and extend through every following point whose gap matches within `1e-9`.
5. Emit that candidate as a range when it contains at least three points, then advance past all of them.
6. Emit a two-point candidate as a range only when its cadence matches the case default `sampling.every_s`, or both points have the same original range block and their gap matches that origin's effective cadence. This prevents two sparse equal points from becoming a misleading giant range merely because any pair is mathematically regular.
7. When a candidate is not range-eligible, add only its first point to a pending `at` group and advance one point. If the current point has no successor, add that final point too. This lets a later three-point cadence be discovered instead of prematurely consuming its first point. Flush the pending `at` group before an emitted range or at the end of the payload run.
8. Before emitting a range, choose `end = min(last + cadence, next_target_timestamp)` when a later target point occurs before `last + cadence`; otherwise use `last + cadence`. Because ranges are half-open, clipping the end to the next point preserves the expanded range while preventing a source-interval overlap with that next point.
9. Round calculated cadence and end values to nine decimal places, matching existing expansion precision.
10. Omit `every_s` when cadence equals the case default within `1e-9`; otherwise include it.
11. Serialize a pending `at` group as `at: [timestamps]`; use scalar `at` for a singleton.
12. Emit blocks ordered by their first timestamp.

The backend returns derived display groups from this exact result. Only emitted range blocks become timeline bands.

Example input points:

```text
0.0 false
0.5 false
1.0 false
1.25 true
2.0 true
4.0 true
```

With default `every_s: 0.5`, the output is:

```yaml
samples:
  - range: [0.0, 1.25]
    expect: false
  - at: [1.25, 2.0, 4.0]
    expect: true
```

The first range uses `1.25` as its half-open end rather than `1.5` because the next differently labeled point starts at `1.25`. It still expands to `0.0`, `0.5`, and `1.0`. The irregular true points stay an `at` list.

For a regular custom cadence:

```text
5.0 true
5.25 true
5.5 true
```

the output is:

```yaml
- range: [5.0, 5.75]
  every_s: 0.25
  expect: true
```

### Sample Block Key Order

New sample blocks use this key order when fields are present:

```text
range or at
every_s
field
expect
compare
comment
```

Inside `compare`, write `mode` before `tolerance`. Omit absent optional fields. Preserve `expect: null` because it is required data.

### Preserving Read-Only Data

On every write, reread the latest YAML as an ordered Python mapping and replace only `targets.<target_id>.samples`. Preserve all other semantic values and existing mapping order, including absent optional sections and extra workflow-target metadata. Do not rebuild the whole case from Pydantic defaults because that would insert omitted defaults and create unnecessary diffs.

Serialize with a small `yaml.SafeDumper` subclass using `sort_keys=False` and `allow_unicode=True`. Add a dedicated wrapper/representer that emits only `range` and multi-value `at` timestamp lists in compact flow style, such as `[0.0, 1.0]`; do not force flow style on expected arrays or arbitrary metadata. The first edit may still change comments, quotes, anchors, other scalar style, and whitespace across the file; this is an accepted tradeoff. The UI must make this behavior clear in README documentation.

Reconstructed blocks are chronological even when the original blocks were not. Normal eval sample indices and `source` labels may therefore change after an edit, as may failure-artifact filenames that include an index. Round-trip equivalence means the same timestamp-sorted list of `(target_id, timestamp_s, expect, field, explicit compare, comment)` points after reloading, not preservation of original block boundaries or sample indices.

The writer does not modify `config.yaml`.

### Candidate Validation And Atomic Write

Do not validate by calling `load_eval_suite` while the original file is still in place, because that would validate the old file rather than the candidate.

The write sequence under the per-case lock is:

1. Read the current case text and parse it as a mapping.
2. Confirm the requested target still exists.
3. Reconstruct and replace only that target's sample blocks.
4. Render candidate YAML in memory.
5. Parse the candidate bytes through `parse_case_yaml`.
6. Expand and validate the candidate through a refactored case loader that accepts a raw mapping or candidate path while retaining the original logical case path for relative video resolution.
7. Require all targets to contain at least one expanded point before accepting a write.
8. Probe the video and run the existing duration checks against all candidate samples.
9. Write the already validated bytes to a uniquely named temporary file in the same directory, flush, and `fsync` it.
10. Preserve the original file's permission bits on the temporary file.
11. Replace the original with `os.replace`.
12. Clean up the temporary file on every failure path and return the accepted document with a new SHA-256 revision.

If any step before `os.replace` fails, the original file remains unchanged. There are no backup files. On POSIX, open and `fsync` the containing directory after replacement; skip this step on platforms that do not expose a supported directory descriptor. Report a file-write failure, but do not fail an already completed replacement solely because this final durability sync is unsupported.

## Technical Architecture

### Overview

```text
+--------------------------- Browser process ----------------------------+
| React application                                                    |
| case/target navigation | video | timeline | table | inspector         |
|             fetch JSON and media from the same origin                 |
+-------------------------------+----------------------------------------+
                                |
                      HTTP on 127.0.0.1
                                |
+-------------------------------v----------------------------------------+
| ReviewServer: ThreadingHTTPServer + explicit request router           |
| static assets | JSON API | write token | byte-range video streaming   |
+-------------------------------+----------------------------------------+
                                |
              +-----------------+------------------+
              |                                    |
+-------------v----------------+     +-------------v-------------------+
| Review document and writer   |     | Existing GlassKit eval modules  |
| per-case locks               |     | schemas | expectations | video  |
| normalization and compaction |     | models  | validation            |
+-------------+----------------+     +-------------+-------------------+
              |                                    |
              +-----------------+------------------+
                                |
                   eval YAML and referenced videos
```

The case YAML on disk is the source of truth. The server should not maintain a second authoritative in-memory suite. Cache only data that is safe to refresh, such as video metadata keyed by resolved path plus file size and modification time.

### Backend Package Layout

Add:

```text
src/glasskit/eval/review/
  __init__.py
  models.py          # Pydantic HTTP request and response models
  documents.py       # suite index, per-case loading, point normalization
  serialization.py   # grouping, YAML reconstruction, candidate validation
  server.py          # HTTP server, router, static/media responses, lifecycle
  static/            # committed Vite build output
```

Use `models.py`, not `types.py`, to avoid shadowing the standard library module name. Keep HTTP concerns out of document and serialization modules so their behavior is unit-testable without sockets.

Expected existing-file changes are:

- `src/glasskit/cli.py`: add the `review` Typer command and lifecycle/error handling.
- `src/glasskit/eval/schemas.py`: add explicit sample comments.
- `src/glasskit/eval/models.py`: retain comments on expanded sample expectations without exposing them to adapters.
- `src/glasskit/eval/expectations.py`: expose reusable case discovery/loading/expansion helpers without changing eval behavior.
- `pyproject.toml`: ensure static assets are packaged.
- `README.md`: document command, workflow, comment field, autosave rewrite behavior, and frame caveat.
- `AGENTS.md`: add frontend development and verification commands.
- Root CLI CI and release workflows: build and verify frontend assets before Python packaging.

### Frontend Workspace

Add a separate contributor workspace:

```text
review-ui/
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  index.html
  src/
    main.tsx
    app/
    api/
    components/
    state/
    timeline/
    styles/
```

Use npm because the repository already uses npm and commits lockfiles. Use the repository's CI Node version, currently Node 24.

Frontend runtime dependencies are `react`, `react-dom`, and `lucide-react`. Use Vite and TypeScript for development, and Vitest plus React Testing Library for focused frontend tests. Do not add a component framework, CSS-in-JS runtime, state library, router, data-fetching library, timeline package, or heavyweight code editor in this implementation.

Use React context plus `useReducer` for selected case, selected target, video state, normalized case drafts, selected point, zoom, lane mode, and save queue status. Keep pure grouping-independent display helpers in ordinary TypeScript modules so they can be tested directly.

Vite development uses a proxy for `/api` and case video requests to a separately running Python review server. Production uses the packaged same-origin assets. No CORS support is needed.

`npm run build` outputs directly to `src/glasskit/eval/review/static/`. Built assets are committed so source distributions and release jobs can build Python packages without fetching npm dependencies. The build must be deterministic enough for CI to rebuild and fail on a dirty static directory.

### Why The Standard Library Server Is Sufficient

The server has a small fixed route set, no remote deployment, no authentication database, no WebSockets, no multipart upload, and no server-rendered HTML. `ThreadingHTTPServer` avoids a runtime framework and ASGI server dependency while allowing media and API requests concurrently.

The implementation must still deliberately provide routing, JSON body limits, error mapping, media byte ranges, content types, cache headers, security headers, clean shutdown, and quiet logging. If this code becomes materially more complex than the feature itself, switching to Starlette and Uvicorn is an acceptable later architecture change, not a requirement for this implementation.

Load packaged static files through `importlib.resources.files("glasskit.eval.review").joinpath("static")` rather than assuming a source-checkout path. Build an allowlisted static-resource map from that directory at startup and never translate an arbitrary URL directly into a filesystem path.

### Server Lifecycle

Construct the server on `127.0.0.1`, bind before opening the browser, then run `serve_forever` on the command thread. Use daemon request threads so shutdown cannot hang on an abandoned browser connection. On `KeyboardInterrupt`, call `shutdown` and `server_close`, then exit successfully.

Generate one cryptographically random write token per process. Return it in the suite bootstrap response. Every mutating request must include it in `X-GlassKit-Write-Token`. Combined with loopback binding, same-origin browser policy, no CORS, and JSON `PUT` requests, this reduces the chance that an unrelated web page can modify local YAML.

Validate the `Host` header as loopback with the bound port. Send `Content-Security-Policy` that permits only packaged same-origin scripts, styles, images, media, and connections; `X-Content-Type-Options: nosniff`; and `Referrer-Policy: no-referrer`. Do not load fonts, scripts, telemetry, or assets from a CDN.

### Video Streaming

`GET` and `HEAD` on the case video endpoint support:

- Full responses with `200`.
- One `bytes=` range with `206`.
- Open-ended and suffix ranges.
- `Accept-Ranges: bytes`.
- Correct `Content-Length`, `Content-Range`, and media content type.
- `416` with the correct wildcard `Content-Range` for invalid or unsatisfiable ranges.

Multiple ranges are not needed and receive `416`. Stream in bounded chunks instead of reading the full video into memory. Resolve video only through the loaded case map; never accept a filesystem path from a query or route parameter.

## HTTP API

### Conventions

All API routes are under `/api`. JSON uses UTF-8 and snake_case names. Pydantic transport models forbid extra request fields, and response serialization uses `allow_nan=False`. Successful API responses send `Cache-Control: no-store`. Static filenames containing a Vite content hash use `Cache-Control: public, max-age=31536000, immutable`; `index.html` uses `no-store`. The video endpoint uses normal range-compatible cache validators.

This is a private, same-package API between the bundled frontend and backend, not a promised public integration surface. Keep request and response models explicit and tested, but do not add URL versioning until another client needs compatibility across package versions.

Limit JSON request bodies to `2 MiB` initially and return `413` when exceeded. Require `Content-Type: application/json` for PUT requests.

Errors have one shape:

```json
{
  "error": {
    "code": "invalid_samples",
    "message": "Target samples are invalid.",
    "details": [
      {
        "path": "points.3.timestamp_s",
        "message": "duplicates the point at 1.5 seconds"
      }
    ]
  }
}
```

Use appropriate status codes: `400` malformed input, `403` missing or invalid write token, `404` unknown case/target, `409` when current disk structure makes the requested target replacement impossible, `413` oversized body, `415` wrong content type, `422` valid JSON that fails eval validation, and `500` unexpected local I/O failures. User-facing messages must include enough path context to act on without exposing arbitrary files outside the eval suite.

Validation issues in successful case documents use `{ "code": str, "message": str, "path": str | null, "severity": "error" | "warning", "repairable": bool }`. `load_error` uses the same `code`, `message`, and optional `details` shape as an API error, without the outer `error` key.

### `GET /api/suite`

Returns bootstrap state and refreshes case summaries from disk without probing every video:

```json
{
  "eval_dir": "/absolute/path/to/eval",
  "write_token": "process-random-token",
  "config_source_yaml": "thresholds:\n  min_pass_rate: 0.9\n",
  "cases": [
    {
      "id": "case-001.yaml",
      "name": "case-001",
      "file_name": "case-001.yaml",
      "description": "Bracket installation",
      "target_count": 2,
      "point_count": 18,
      "status": "ready",
      "error": null
    }
  ]
}
```

The case ID is the exact filename including `.yaml` or `.yml`; clients percent-encode it in route segments. The server looks it up in its discovered case map and never joins an untrusted route value into a path.

Target IDs and filenames may contain characters that need URL encoding, including a slash in a target ID. Split the raw URL path into route segments before percent-decoding each segment, then perform an exact map lookup. Never decode the full path before routing.

Point counts require schema parsing and expansion but not video probing, video decoding, or adapter loading. `status` is `ready` when points can be normalized and `blocked` when YAML, schema, or overlap errors prevent normalization. A blocked summary includes its error and leaves unavailable counts null.

### `GET /api/cases/{case_id}`

Reloads the case, probes its video, and returns the review document:

```json
{
  "id": "case-001.yaml",
  "name": "case-001",
  "revision": "sha256-of-current-source-bytes",
  "status": "ready",
  "editing_enabled": true,
  "load_error": null,
  "description": "Bracket installation",
  "source_yaml": "video: ...\n",
  "video": {
    "url": "/api/cases/case-001.yaml/video",
    "display_path": "../../../recordings/task-01.mp4",
    "duration_s": 18.2,
    "width": 1920,
    "height": 1080,
    "frame_count": 546
  },
  "targets": [
    {
      "id": "bracket_seated",
      "label": "Bracket seated",
      "details_yaml": "label: Bracket seated\nconfig:\n  prompt_id: workflow.bracket_seated\n",
      "points": [],
      "display_groups": []
    }
  ],
  "validation_issues": []
}
```

`details_yaml` contains read-only target metadata without samples. `source_yaml` is authoritative for showing everything else. Do not try to JSON-encode arbitrary adapter config values that PyYAML may have constructed as non-JSON Python types.

For a known, readable case, this endpoint always returns a document with HTTP `200`, including when review is blocked. `status` is `ready` for a normally valid case, `repairable` when normalized points exist but one or more targets are empty or timestamps exceed duration, and `blocked` when YAML/schema/overlap errors prevent normalization or the video cannot be resolved and probed. `editing_enabled` is true for `ready` and `repairable`, and false for `blocked`. A blocked document keeps `source_yaml`, sets unavailable structured fields to null or empty arrays, and supplies `load_error` plus `validation_issues`. Unknown IDs return `404`; an operating-system failure that prevents reading a discovered file returns `500`.

The document builder must separate schema/point normalization from video resolution enough to return source and normalized targets when video probing fails. A repairable PUT is accepted only when the candidate resolves every case validation issue, after which the returned status is `ready`.

### `GET|HEAD /api/cases/{case_id}/video`

Streams the resolved video as described under "Video Streaming". It has no general path parameter beyond the known case ID.

### `PUT /api/cases/{case_id}/targets/{target_id}/samples`

Replaces all points for one existing target:

```json
{
  "points": [
    {
      "id": "client-opaque-id",
      "timestamp_s": 1.5,
      "expect": true,
      "field": null,
      "compare": {
        "mode": null,
        "tolerance": null
      },
      "comment": null,
      "origin": null
    }
  ]
}
```

Validate request IDs for uniqueness within the request but do not persist them. Validate all JSON-like values recursively and reject non-finite numbers. The route target is authoritative; a point has no target field.

Under the case lock, reload the latest source, replace the requested target, validate and write atomically, then return the same case-document shape as `GET`, preserving request point IDs and recomputing their origins from the accepted blocks. Returning the complete accepted document keeps range bands, YAML source, counts, video metadata, and revision synchronized.

The server must not accept an empty list when it would make the candidate invalid for normal eval loading.

### `POST /api/cases/{case_id}/validate`

Reloads and validates the current on-disk case without writing. It returns revision and validation issues. The UI uses it for an explicit refresh/validate action and after detecting an external revision change.

This endpoint requires the write token because it is a non-idempotent HTTP method even though it does not mutate disk. It does not load an adapter or run evaluation.

### Static Routes

`GET /` and known Vite asset paths serve packaged files. Unknown non-API `GET` paths fall back to `index.html`; unknown `/api` paths always return JSON `404` and never fall through to the SPA.

## Validation Policy

Frontend validation is for immediate feedback; backend validation is authoritative.

The backend checks:

- JSON request shape and body limits.
- Unique UI IDs.
- Finite, nonnegative timestamps.
- Unique timestamps per target within `1e-9`.
- JSON-like, finite expected values.
- Nonblank optional field and comment values after normalization.
- Supported comparison mode and nonnegative finite tolerance.
- Existing target and case identity.
- At least one sample in every target after the edit.
- Existing schema rules.
- Expansion and source-overlap rules.
- Video existence, type, probe success, and sample duration bounds.

Do not add stricter mode-to-expectation schema validation globally in this feature because existing accepted evals may rely on the current permissive schema. The type-aware UI guides new values while the core comparison behavior remains backward compatible.

## Accessibility And Usability Requirements

- Every command is keyboard reachable and has a visible focus state.
- Marker buttons have useful accessible names and do not rely on color alone.
- Native video controls remain enabled.
- Inputs have persistent labels; placeholders are not labels.
- Save, validation, and selected states use text or icons in addition to color.
- Tooltips do not contain essential information unavailable elsewhere.
- Compact controls have at least a practical 32 px pointer target, while narrow timeline markers use an invisible larger hit area.
- Long target IDs, paths, expected strings, and JSON wrap or truncate with a tooltip without changing fixed lane and toolbar dimensions.
- Reduced-motion preference disables nonessential transitions.
- No UI element overlaps another at supported desktop sizes.

## Packaging And Development Workflow

### Contributor Commands

The final implementation should support two development modes.

Packaged/static mode:

```bash
cd cli
uv run glasskit eval review --eval-dir tests/fixtures/eval_suites/two-state
```

Frontend development mode:

```bash
cd cli
uv run glasskit eval review --eval-dir tests/fixtures/eval_suites/two-state --port 8765 --no-open
```

In another shell:

```bash
cd cli/review-ui
npm ci
GLASSKIT_REVIEW_BACKEND=http://127.0.0.1:8765 npm run dev
```

`vite.config.ts` reads `GLASSKIT_REVIEW_BACKEND` and proxies `/api` to that origin with `changeOrigin: true` so backend Host validation sees the backend address. It defaults to `http://127.0.0.1:8765`. Do not enable broad backend CORS just for development.

Required npm scripts:

```text
dev        Start Vite
build      Type-check and build packaged assets
test       Run Vitest once
test:watch Run Vitest in watch mode
check      Type-check and run tests
```

### Python Package

Place built files under the `glasskit` package so `uv_build` includes them as package data. Verify this rather than assuming it: inspect the wheel and source distribution in tests or release checks and assert that `glasskit/eval/review/static/index.html` plus referenced hashed assets exist.

Runtime users must not need npm, Node.js, a network connection, a system `ffmpeg` executable, or a new web-framework dependency. PyAV remains the existing video dependency.

### CI And Release

Extend the CLI CI and release jobs to install Node 24, run `npm ci`, run `npm run check`, run `npm run build`, and fail if committed static output changes. Run this before `uv build`.

Keep the existing Python matrix, offline pytest requirement, type checking, Ruff checks, and CLI help smoke tests. Add a wheel/sdist smoke check that imports the review static resource or starts the server in a controlled test and fetches `/`.

The release build should consume committed, verified assets rather than depending on an unrecorded local build. Update `PUBLISHING.md` if the release checklist gains required frontend commands.

## Test Plan

Add a committed `tests/fixtures/eval_suites/review/` suite that reuses the existing tiny synthetic videos and contains at least two cases, multiple targets at overlapping times, ranges with default and custom cadence, scalar and structured expectations, comparison settings, workflow/target metadata, thresholds, and explicit comments. Keep malformed, empty-target, and write-failure variants generated in temporary directories so the committed fixture remains valid. Do not add a realistic or private recording.

### Python Unit Tests

Add focused tests for:

- Parsing and normalizing scalar `at`, list `at`, and `range` blocks.
- Explicit sample comments, including expansion and blank rejection/omission.
- Deterministic point IDs and origin metadata.
- Structural payload equality, including object key order and boolean-versus-number distinctions.
- Default-cadence range reconstruction.
- Custom-cadence range reconstruction.
- Two-point default and source-origin range rules.
- Sparse two-point values remaining `at`.
- Irregular points becoming an `at` list.
- Range end clipping at the next differently labeled point.
- Group splits for expectation, field, compare, tolerance, and comment changes.
- Nine-decimal arithmetic normalization.
- Duplicate, negative, non-finite, empty-target, overlap, and over-duration rejection.
- Semantic preservation of video, description, sampling, workflow, target order, config, and thresholds.
- Omitted Pydantic defaults remaining omitted.
- Failed candidate validation leaving original bytes untouched.
- Atomic replacement preserving file permission bits.
- Concurrent writes to two targets preserving both accepted changes.

### Server And CLI Tests

Use stdlib HTTP clients and Typer's test runner. Cover:

- `review` appears in `glasskit eval --help` with the specified options.
- Initial case and target validation.
- Available-port binding and `--no-open`.
- Suite bootstrap with valid and invalid case summaries.
- Case document JSON and read-only YAML text.
- Unknown and path-like case IDs returning `404`.
- Missing or incorrect write token returning `403`.
- Target replacement success and structured validation failure.
- Oversized and wrong-content-type requests.
- Full video GET and HEAD.
- Prefix, open-ended, and suffix byte ranges.
- Invalid, unsatisfiable, and multiple ranges.
- Static index and hashed asset serving with correct cache and security headers.
- Clean server shutdown.

Tests must remain offline and use temporary copies of committed synthetic fixtures. Ordinary pytest must not require a system `ffmpeg` command.

### Frontend Tests

Use Vitest and React Testing Library for behavior with meaningful regression risk:

- Case and target selection.
- Timeline point positioning and displayed range bands from backend groups.
- Zoom calculations and scroll anchoring helpers.
- Marker/table/inspector selection synchronization.
- Seek readiness waits for the current `seeked` event and, when supported, prefers the current `requestVideoFrameCallback()` generation without hanging past the `500 ms` fallback.
- Rapid consecutive seeks cancel or ignore stale events, callbacks, and timeouts, while browsers without `requestVideoFrameCallback()` fall back to `seeked`.
- Presented-frame `mediaTime` is displayed diagnostically and never mutates the sample timestamp.
- New-point defaults and duplicate-time selection.
- Type-aware expectation controls.
- Comparison reset after incompatible type change.
- JSON draft parsing and inline errors.
- Shortcut handling and input-focus exclusion.
- Per-case save serialization, coalescing, and stale-response ordering.
- Failed-save draft retention and retry/reload behavior.
- Last-sample delete protection.

Do not duplicate backend compaction logic in frontend tests. The frontend renders `display_groups` supplied by the backend.

### Manual Acceptance

Use a copied fixture so the repository fixture is not modified:

1. Launch the packaged UI and confirm the browser opens at the printed loopback URL.
2. Play, pause, seek, change playback rate, and use every visible shortcut.
3. Click markers rapidly across multiple target lanes and confirm target focus, video time, table row, inspector, and preview-ready state stay synchronized without a stale frame winning.
4. Create a point, edit each expectation type, edit field/compare/tolerance/comment, move its timestamp, and delete another point.
5. Confirm save state transitions and inspect the rewritten YAML.
6. Confirm range bands match emitted range blocks.
7. Run `glasskit eval validate` and `glasskit eval list-samples` on the edited copy.
8. Trigger invalid JSON, a duplicate timestamp, a simulated write failure, and a browser refresh with unsaved data.
9. Test Fit, 2x, 4x, and 8x timeline modes at desktop widths near 1024, 1280, and 1600 px.
10. In a browser with `requestVideoFrameCallback()`, confirm the shown-frame PTS appears after seeking and does not alter the sample time; feature-disable it in developer tools or a test build and confirm the `seeked` fallback.
11. Review the nonzero-PTS `offset-start-64x64.mp4` fixture and confirm sample-time seeking remains usable while any browser timeline difference is reported honestly.
12. Build wheel and sdist, install each in isolation, launch review with `--no-open`, and fetch the packaged index.

After code changes, run the repository-required Python checks:

```bash
uv run ty check
uv run pytest
uv run ruff check --fix
uv run ruff format
uv run glasskit --help
uv run glasskit eval --help
```

Also run the frontend `npm run check` and `npm run build`.

## Delivery Plan

### Phase 1: Shared Document And Serialization Core

- Add the explicit sample comment schema and tests.
- Refactor case loading so review and normal eval share parsing, expansion, overlap, and video-path rules.
- Implement review transport models, point normalization, compaction, candidate validation, and atomic target replacement.
- Add complete writer unit tests before building HTTP behavior.

Exit gate: a pure Python test can load a fixture target into points, edit those points, write a temporary case, reload it through normal eval loading, and prove point-level equivalence.

### Phase 2: Local Server And CLI

- Add suite indexing with per-case errors.
- Implement API routing, structured errors, write token, case locks, video ranges, static serving, and security headers.
- Add `glasskit eval review` with exact launch and shutdown behavior.
- Serve a minimal checked-in placeholder index until the React build lands.

Exit gate: server and CLI tests pass, a browser can seek the fixture video, and a direct API target replacement atomically changes a copied YAML.

### Phase 3: Read-Only React Review Experience

- Scaffold `review-ui`.
- Implement application shell, case/target sidebar, native video, review transport, timeline lanes and zoom, samples table, inspector display, source drawers, responsive behavior, and shortcuts that do not mutate.
- Add frontend unit tests for selection, timeline, zoom, and keyboard behavior.

Exit gate: a user can review every fixture point, click through targets, and inspect all case/eval YAML values without opening another tool.

### Phase 4: Editing And Autosave

- Implement create, type-aware expectation editing, timestamp editing, field/compare/tolerance/comment editing, and delete.
- Implement local validation, per-case save queue, coalescing, status display, retry, reload, navigation flush, and unload protection.
- Render backend-derived groups after every accepted save.
- Add failure and concurrency tests.

Exit gate: the full primary workflow works against a copied fixture and normal eval validation accepts every saved result.

### Phase 5: Packaging, CI, Documentation, And Product Polish

- Build and commit static assets.
- Ensure wheel and sdist include them.
- Add frontend CI/release checks.
- Update README, AGENTS, and PUBLISHING as needed.
- Verify accessibility, long-value layout, supported desktop widths, browser error states, and manual acceptance steps.

Exit gate: an isolated install can launch the review UI without Node, all Python and frontend checks pass, and the definition of done below is satisfied.

## Definition Of Done

- `glasskit eval review` is documented and present in CLI help.
- The command binds only to loopback, opens after listening, prints its URL, and shuts down cleanly.
- Cases and targets are navigable, filterable, and shown in source order.
- The original video seeks through a byte-range endpoint.
- Point selection uses `currentTime`, waits for the current seek to present, and cannot be completed by stale events from an earlier selection.
- The transport distinguishes authoritative sample time from browser-presented frame PTS when the browser exposes it.
- The UI and documentation describe video as a best-effort browser preview and never promise the same frame chosen by PyAV.
- Every expanded point is visible in a target lane and table.
- Point selection synchronizes video, timeline, table, and inspector.
- All agreed keyboard shortcuts are visible and work outside form controls.
- Users can create, edit, move, and delete points with type-aware validation.
- Existing empty targets can receive a first point, and the UI cannot save a newly empty valid target.
- Autosave is serialized per case, survives rapid edits without stale overwrites, and has clear saved, pending, invalid, and failed states.
- YAML writes replace only one target's samples semantically, validate the candidate rather than the old file, and are atomic.
- Reconstructed ranges expand to exactly the submitted points and never overlap a following point.
- Optional explicit comments survive load, edit, save, and reload.
- All read-only case and eval YAML is visible.
- Existing valid files are untouched until an edit.
- Cases written by the UI pass normal eval loading and video timestamp validation.
- Static assets are present in wheel and sdist, and runtime use requires no Node installation.
- Default Python tests remain offline and do not require a system `ffmpeg`.
- README explains autosave, formatting loss, local-only behavior, video codec support, and the browser-versus-PyAV frame caveat.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Browser frame differs from eval frame | Show sample time and browser-presented PTS separately, wait for the completed presentation, and document the accepted best-effort limitation |
| Browser cannot play a CLI-supported container or codec | Show a specific disabled-video error; do not silently transcode |
| Rapid autosaves lose edits across targets | Serialize writes per case in frontend and server; reread under lock |
| YAML rewrite creates a large diff | Replace only sample data semantically, preserve mapping order and omissions, document PyYAML formatting behavior |
| Automatic ranges change sample meaning | Share expansion rules, use conservative deterministic grouping, clip range end, and assert round-trip point equivalence |
| Invalid request corrupts a case | Validate candidate bytes before same-directory atomic replacement |
| Malicious page targets localhost | Loopback-only bind, no CORS, Host validation, random write token, JSON PUT, CSP |
| Frontend assets missing from package | Commit build output and verify wheel/sdist contents in CI and release |
| Stdlib server grows unwieldy | Keep routing isolated; adopt Starlette/Uvicorn later only when measured complexity justifies runtime dependencies |

## Deferred Work

- PyAV-backed eval-frame still preview and frame-step controls, reconsidered only if representative recordings show material labeling mistakes from browser/PyAV differences.
- Browser-compatible transcoding or proxy playback for unsupported codecs.
- Importing eval result JSON and jumping directly among failed samples.
- Showing observed values or running adapters from the UI.
- Editing case, target, workflow, sampling, threshold, or eval-level metadata.
- Creating/deleting cases and targets.
- Multi-tab conflict detection or optimistic concurrency rejection.
- Persistent undo, backups, or Git integration.
- Timeline virtualization based on measured large-suite performance.
- Remote serving or collaborative review.
