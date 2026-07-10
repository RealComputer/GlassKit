# GlassKit Eval Review UI

The source code is the source of truth for shipped behavior. This file records only the enduring product problem, goals, and work that has not been implemented.

## Problem

Recorded-video eval expectations connect structured YAML values to precise moments in a video. Reviewing those expectations in a media player and text editor requires keeping two tools synchronized, translating timestamps manually, and repeatedly switching context. That makes even simple verification slow and turns corrections into an error-prone editing task.

The review UI should keep the video, expanded sample schedule, expected values, and editing controls together. A user should be able to move from a timestamp reported by `glasskit eval run` to the relevant case and target, inspect the moment, correct the expectation or timestamp, and continue reviewing without manually editing YAML.

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

## Remaining Work

### Unfinished Original Scope

These behaviors were part of the original review UI plan but are not fully implemented in the current source.

- Complete conditional video request handling for the emitted `ETag` and `Last-Modified` validators, including correct `If-Range` behavior when the underlying video changes.

### Deferred Capabilities

The following capabilities remain deferred unless user feedback, representative recordings, or measured performance makes them worth prioritizing.

- Add an optional PyAV-backed still preview and frame-step controls for cases where browser and eval frame selection differ materially.
- Add browser-compatible transcoding or proxy playback for source videos whose container or codec the browser cannot play.
- Import eval result JSON and navigate directly among failed samples, including observed values and failure artifacts.
- Run adapters or evals from the review UI.
- Edit case metadata, video paths, target IDs, labels, target configuration, workflow metadata, sampling defaults, thresholds, and eval-level configuration.
- Create and delete cases or targets.
- Preserve YAML presentation details such as syntax comments, anchors, quoting, flow style, and hand formatting when edited sample data is written.
- Detect and resolve conflicting edits from other tabs or external processes instead of using last-writer-wins behavior.
- Add persistent undo, backups, or Git integration.
- Virtualize large sample tables and timelines if profiling shows a real performance need.
- Cluster dense timeline markers if representative suites show that focus, table, and previous/next navigation are insufficient.
- Support remote serving, authentication, multi-user collaboration, or shared review sessions.
- Provide a mobile-first layout and interaction model.
