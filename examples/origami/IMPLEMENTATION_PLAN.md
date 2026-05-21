# Origami Guide Implementation Plan

## Goal

Rebuild this example from a mocktail coach into a silent, server-authoritative
origami guide for Rokid Glasses.

The wearer sees a 7-step origami HUD. Each step shows a wide reference image,
the backend proactively checks the camera view with Overshoot, and the workflow
advances automatically after two consecutive positive detections. Manual step
navigation remains available by swipe. Tap toggles automatic camera checking.
Double-tap starts the guide from the initial screen and resets to the initial
screen after completion.

The browser demo shows a realtime composed view of the glasses camera POV and
HUD/screen output, with controls equivalent to the glasses controls.

## Confirmed Decisions

- UI language: English only.
- Audio: silent. Remove OpenAI Realtime API and all spoken guidance.
- Overshoot API: keep v0.2 for now because the existing integration should still
  work.
- Browser demo: single-device only. Attach to the current/latest glasses session.
- Screen capture: actual Android screen capture was tested on Rokid and is not
  available to this normal app without privileged MediaProjection permission.
  The implementation now uses backend-rendered browser HUD composition instead.
- Assets: copy `tmp/step-imgs/` and `tmp/ref-imgs/` into tracked Android/backend
  asset locations during implementation.
- Control transport: if a WebRTC connection exists, use a data channel instead of
  adding another control WebSocket.
- Auto-check pause: when automatic progression is off, stop Overshoot inference
  work rather than continuing to spend tokens/cycles.
- Completion stabilization: any `false` resets the consecutive true counter;
  two consecutive `true` observations pass the active step.
- During the 2-second "Done!" hold, manual controls are accepted and cancel any
  pending automatic delayed advance.

## Existing Code To Reuse

- Current Android `OvershootSessionClient.kt` already captures the Rokid camera
  with WebRTC and uses hardware encoder factories.
- `../rokid-rfdetr/` has the better Python backend receive pattern:
  - `aiortc` terminates Android WebRTC.
  - Backend prefers inbound H.264.
  - Data channel JSON carries app events.
  - Latest-frame processing avoids stale queues.
- `../../skills/glasskit/SKILL.md` and references confirm Rokid input mapping:
  - Tap: `KEYCODE_ENTER`
  - Double-tap: back handling / `KEYCODE_BACK`
  - Swipe forward: `KEYCODE_DPAD_DOWN`
  - Swipe backward: `KEYCODE_DPAD_UP`
- `tmp/make_reference_video.py` shows the intended reference-composition style:
  a top header with label and reference image over the camera frame.

## Target Architecture

```text
Rokid Android app
  - HUD rendering
  - touchpad input
  - camera capture: 1024x768@15 capture, 5 fps WebRTC output
  - one WebRTC PeerConnection with:
      track 1: camera
      data channel: session-events

Backend FastAPI app
  - aiortc receiver for Rokid media/data channel
  - authoritative origami session state machine
  - latest camera frame store
  - reference-frame composer for Overshoot input
  - outgoing aiortc/WebRTC stream to Overshoot v0.2
  - Overshoot result websocket + keepalive
  - browser demo page and browser WebRTC viewer

Browser demo
  - receives composed realtime video over WebRTC
  - sends controls over data channel
  - shows buttons for start/reset, next, previous, auto toggle
```

## Backend Workflow Model

Replace the recipe/mocktail model with a fixed origami workflow.

Recommended backend data shape:

```json
{
  "title": "Origami Guide",
  "steps": [
    {
      "id": "step_1",
      "number": 1,
      "hud_image": "step-imgs/1.png",
      "reference_image": "ref-imgs/1.jpg",
      "prompt": "Return true if the origami model on the tray matches the reference shape; otherwise, return false."
    }
  ]
}
```

The backend state should include:

- `phase`: `WAITING_FOR_START`, `CONNECTING`, `GUIDING`, `STEP_DONE`,
  `COMPLETED`, `ERROR`
- `step_index`: 0-based active step
- `auto_check_enabled`: boolean
- `true_streak`: integer
- `done_until`: monotonic timestamp or delayed-task handle for the 2-second hold
- `media_ready`: camera/data channel state
- generation counters for media/Overshoot/step changes

State transitions:

- Double-tap from start: begin session at step 1.
- Tap during guidance: toggle `auto_check_enabled`.
- Swipe forward/backward: move one step, cancel any pending done delay, reset
  `true_streak`.
- Overshoot `true`: increment `true_streak`; pass the step at 2.
- Overshoot `false`: reset `true_streak` to 0.
- Step pass: publish `STEP_DONE`, show `Done!` for 2 seconds, then advance unless
  manual input changes state first.
- Last step pass: publish `COMPLETED`; double-tap resets to start.

## Android App Plan

### UI

Replace the mocktail layout with a monochrome origami layout:

```text
Origami Guide

Step 1/7:
[wide step image]
Done!       only during the 2-second completion hold



Double tap: start/reset
Tap: auto check on/off
Swipe: previous/next
```

Implementation notes:

- Use black background and white foreground; Rokid renders this as green on
  transparent.
- Copy `tmp/step-imgs/*.png` into `rokid/app/src/main/res/drawable-nodpi/`.
- Use an `ImageView` for the active step image with `adjustViewBounds` and
  `fitCenter`.
- Keep text compact enough for the 480x640 portrait HUD.
- Do not render speech transcript UI.

### Input

- Handle tap with `KEYCODE_ENTER`: toggle auto-check only while guiding.
- Handle swipe forward with `KEYCODE_DPAD_DOWN`: manual next.
- Handle swipe backward with `KEYCODE_DPAD_UP`: manual previous.
- Handle double-tap/back by intercepting back dispatch:
  - start from initial screen
  - reset to initial screen after completion
  - ignore the default app-close behavior for this app flow

### Media And Control

Create one replacement client, likely `OrigamiSessionClient.kt`, instead of
keeping separate Overshoot/OpenAI clients.

The client should:

- Create one `PeerConnection` with Unified Plan.
- Add camera track:
  - capture `1024x768@15`
  - call `adaptOutputFormat(1024, 768, 5)` so encoder/network output is 5 fps
  - prefer hardware H.264 via `DefaultVideoEncoderFactory`
- Add `session-events` data channel before creating the offer.
- Send SDP to backend with `application/sdp`.
- Queue JSON control messages until the data channel is open.
- Parse backend state messages and render HUD from those messages only.

## Backend Plan

### Dependencies

Add backend dependencies:

- `aiortc` for WebRTC receive/send.
- `av`, `numpy`, and `pillow` for frame conversion/composition. `aiortc` will
  likely bring `av`, but list direct dependencies if imported directly.

Keep existing:

- `fastapi[standard]`
- `httpx`
- `websockets`

Remove OpenAI dependencies/configuration paths from runtime code and docs.

### Session Transport

Replace `/session/control`, `/session/{id}/vision`, and `/session/{id}/realtime`
with a simpler media endpoint:

- `POST /session/media`
  - request body: Android offer SDP
  - response body: backend answer SDP
  - creates/replaces the single active Rokid session

Backend `aiortc` behavior:

- Accept the incoming camera video track and prefer H.264.
- Accept the client-created data channel.
- Store the latest camera frame.
- Close old peer connections when a new glasses session starts.
- Send initial HUD/session state over the data channel when it opens.

Data-channel messages from Android/browser:

- `session.start`
- `session.reset`
- `manual.next`
- `manual.prev`
- `auto.toggle`
- optional `client.media_ready` / track metadata

Data-channel messages from backend:

- `session.ready`
- `hud.state`
- `hud.error`
- optional `debug.vision_state`

### Overshoot v0.2 Path

The backend should no longer broker the Rokid SDP directly to Overshoot because
the backend must compose the reference image into the camera frame first.

Use a backend-originated outgoing WebRTC stream to Overshoot:

1. Backend receives camera frames from Rokid.
2. Backend composes each sampled camera frame with the active step reference
   image using the `tmp/make_reference_video.py` header style.
3. Backend exposes that composed frame sequence through an `aiortc`
   `MediaStreamTrack`.
4. Backend creates an SDP offer for Overshoot v0.2 `/streams` with:
   - `source: {"type": "webrtc", "sdp": backend_offer_sdp}`
   - `mode: "frame"`
   - `processing: {"interval_seconds": 0.5}`
   - active step prompt
   - output schema `{"type": "boolean"}`
5. Backend sets Overshoot's answer SDP on its outgoing peer connection.
6. Backend listens to Overshoot's stream websocket for structured results.

When auto-check is disabled:

- Stop or close the Overshoot runtime for the active session.
- Keep receiving Rokid camera frames for the browser demo.

When auto-check is re-enabled:

- Start a fresh Overshoot runtime for the active step/generation.

When the step changes:

- Reset true streak.
- Recompose with the new reference image.
- Prefer closing/restarting the Overshoot stream for a clean generation boundary,
  unless prompt patching plus generation checks is simpler and reliable.

Risk to verify early: confirm Overshoot v0.2 accepts an `aiortc` backend-originated
WebRTC publisher in the same way it accepted Android offers. If that fails, the
fallback is to use Overshoot v1 still-image/chat-completions calls for sampled
composed frames, or temporarily stream Android camera directly without reference
composition.

### Browser Demo

Add a static demo page served by FastAPI:

- `GET /demo`: HTML/CSS/JS page.
- `POST /demo/session`: browser offer SDP, backend answer SDP.

Browser `PeerConnection`:

- Receives one composed video track from backend.
- Opens a `demo-events` data channel for controls and state.

Backend viewer composition:

- Use the latest camera frame as the POV and preserve its received dimensions.
- Do not crop or downsize the POV for the browser demo.
- Render the current HUD state in the backend as a green transparent overlay,
  using the same step assets as the glasses, then scale the HUD up to the POV
  size for the browser WebRTC stream.
- Run viewer output at about 5 fps; browser demo latency matters more than high
  quality.

Demo controls:

- Start/reset
- Previous step
- Next step
- Auto-check toggle

All controls should enqueue the same session events as Android controls.

## Asset Plan

During implementation:

- Copy HUD images:
  - from `tmp/step-imgs/*.png`
  - to `rokid/app/src/main/res/drawable-nodpi/origami_step_*.png`
- Copy reference images:
  - from `tmp/ref-imgs/*.jpg`
  - to `backend/assets/ref-imgs/*.jpg`
- Add a backend workflow config:
  - `backend/assets/origami_steps.json`
  - one entry per step, including prompt, HUD image id, and reference image path

Keep `tmp/` as source material/reference only.

## Documentation Updates

After implementation, update:

- `README.md`
  - origami app overview
  - backend run instructions
  - browser demo URL
  - no OpenAI key required
  - backend-rendered demo HUD and Overshoot disable controls
- `AGENTS.md`
  - replace mocktail/OpenAI architecture with origami/Overshoot/backend WebRTC
  - update commands and key files
  - keep required verification commands
- `backend/.env.example`
  - remove `OPENAI_API_KEY`
  - keep `OVERSHOOT_API_KEY` and optional Overshoot settings
- Android strings/package names if desired

## Verification Plan

After backend changes:

```bash
cd backend
uv run ty check && uv run ruff check --fix && uv run ruff format
```

After Android changes:

```bash
cd rokid
./gradlew :app:assembleDebug
```

Manual verification:

- App launch shows "Origami Guide" and "Double tap to start".
- Double-tap starts step 1 instead of closing the app.
- Tap toggles auto-check on/off and backend stops/restarts Overshoot runtime.
- Swipe forward/back changes steps and cancels pending 2-second done delay.
- Two consecutive `true` Overshoot results show `Done!` for 2 seconds, then
  advance.
- A `false` result resets true streak.
- Step 7 completion shows final state; double-tap returns to initial screen.
- Browser `/demo` shows live camera POV with a backend-rendered green HUD overlay.
- Browser buttons produce the same state transitions as glasses controls.
- Backend teardown closes Rokid peer, browser peers, and Overshoot streams.

## Implementation Order

1. Replace docs/config scaffolding and copy assets.
2. Add backend origami workflow/state types with pure unit-testable transition
   helpers.
3. Replace backend signaling with `aiortc` `/session/media` and data-channel
   state/control.
4. Refactor Android to the origami HUD and data-channel-driven state.
5. Add camera-only backend receive path and verify H.264/5 fps behavior.
6. Add browser demo WebRTC viewer and controls.
7. Add backend reference composition and outbound Overshoot v0.2 runtime.
8. Connect Overshoot boolean results to the two-hit step progression policy.
9. Run verification commands and update README/AGENTS.

## Main Risks

- Overshoot v0.2 may not behave identically with an `aiortc` backend publisher;
  test this before investing deeply in viewer polish.
- Browser viewer composition may need frame pacing/backpressure handling so a slow
  browser does not stall camera ingestion or Overshoot inference.
