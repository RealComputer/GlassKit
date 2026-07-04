# Project Overview

This project is a server-authoritative origami guide for Rokid Glasses. The glasses show a visual folding guide on the HUD, stream camera video to the backend, and receive backend-driven state updates over a WebRTC data channel. The backend checks each fold with Overshoot and drives the fixed origami workflow.

- Rokid Glasses are Android-based smart glasses with a camera, monochrome HUD, and temple touchpad.
- Overshoot is a vision-language model inference API for live video.

# Architecture

- The Android client stays thin: it renders the HUD, handles camera permission, and maps touchpad gestures into backend commands.
- The FastAPI backend owns the active session, current step, HUD state, manual and automatic progression, auto-check availability, and Overshoot runtime.
- Overshoot only sees backend-composed video, not a direct Rokid stream.
- Browser `/demo` is a backend-connected viewer/controller. It approximates the wearer's view by reconstructing the Rokid HUD over the latest camera frame, but it is not a separate workflow owner.
- Turning auto check off stops Overshoot while keeping the device and browser media sessions alive. `ORIGAMI_AUTO_CHECK_ENABLED=false` disables Overshoot stream creation for the whole backend process.
- The latest Overshoot API uses LiveKit publishing plus explicit chat-completion prompts. The backend creates an Overshoot stream, publishes backend-composed camera/reference video into the returned LiveKit room, polls stream readiness until the first frame is ingested, and then calls `/chat/completions` sequentially with `ovs://streams/<id>?frame_index=-1` image references.
- The backend records the real camera frames sent into the Overshoot path before reference-image composition by default. Recordings are written under `backend/debug/overshoot-inputs` unless `ORIGAMI_OVERSHOOT_INPUT_RECORDING_DIR` overrides the location, and `ORIGAMI_RECORD_OVERSHOOT_INPUTS=false` disables this recording.

## Connection Graph

- `Rokid <-> Backend` WebRTC: camera video upstream plus `session-events` commands and HUD state.
- `Backend -> Overshoot` LiveKit/WebRTC: composed fold-check video.
- `Backend -> Overshoot` HTTP: stream setup, stream status polling, keepalive, chat-completion fold checks, and stream deletion.
- `Browser <-> Backend` WebRTC: demo video plus `demo-events` controls.

## Session Flow

1. Rokid shows the start screen.
2. Double tap opens a backend media session and starts the origami workflow.
3. The backend enters the first step, publishes HUD state, and starts Overshoot when auto check is available.
4. The backend sends composed camera/reference video to the Overshoot LiveKit room.
5. The backend prompts Overshoot chat completions against the latest ingested stream frame, parses the boolean response, and decides whether to advance the step.
6. Swipe controls and browser demo controls send manual navigation commands to the backend.
7. Completion or reset returns the HUD to the start screen.

# Key Files

## Rokid (`./rokid/`)

- `app/src/main/java/com/example/origamiguide/MainActivity.kt`: start screen, touchpad gesture mapping, and HUD rendering.
- `app/src/main/java/com/example/origamiguide/OrigamiSessionClient.kt`: camera WebRTC publishing and `session-events` data channel.
- `app/src/main/res/layout/activity_main.xml`: monochrome Rokid HUD.
- `app/src/main/res/drawable-nodpi/origami_step_*.png`: seven step guide images.
- `app/build.gradle.kts`: `BACKEND_BASE_URL` BuildConfig value from `rokid/local.properties`.

## Backend (`./backend/`)

- `src/main.py`: FastAPI lifecycle and `/session/media`, `/demo`, and `/demo/session` routes.
- `src/session_manager.py`: public session manager, session loop, HUD state, and origami workflow state machine.
- `src/overshoot_runtime.py`: session-scoped Overshoot orchestration, worker tasks, LiveKit reconnect recovery, prompt gating, and runtime cleanup.
- `src/overshoot_client.py`: Overshoot HTTP API client for stream setup/status, keepalive, chat-completion requests, retries, and response parsing.
- `src/overshoot_livekit.py`: LiveKit publisher setup, token refresh, track options, and image-to-video-frame capture helpers.
- `src/overshoot_diagnostics.py`: Overshoot debug composite saving and pre-composition input recording lifecycle.
- `src/fold_check.py`: shared fold-check helpers for reference composition, step loading, and boolean result parsing.
- `src/rtc_media.py`: aiortc peer connection helpers and backend-originated video tracks.
- `src/recording.py`: non-blocking video recording for pre-composition Overshoot input frames.
- `src/rendering.py`: Overshoot reference composition, browser demo composition, and HUD image rendering.
- `src/session_state.py`: session data classes, latest-frame buffer, and grouped Overshoot runtime state.
- `src/origami_config.py`: step config loader.
- `eval_adapter.py`: recorded-video `gk eval` adapter that sends composed sampled frames to Overshoot chat completions without LiveKit.
- `assets/origami_steps.json`: seven step definitions and prompts.
- `assets/step-imgs/*.png`: green browser-demo HUD versions of the step guide images.
- `assets/ref-imgs/*.jpg`: active step reference images used for Overshoot composition.
- `.env.example`: required key and optional Overshoot overrides.

# Commands

## Rokid

`cd rokid` then:

- `./gradlew :app:assembleDebug`: Always run after Android changes

## Backend

`cd backend` then:

- `uv run ty check && uv run ruff check --fix && uv run ruff format`: Always run after backend changes
- `uv run --env-file .env fastapi dev src/main.py --host 0.0.0.0`: start server with env loaded
- `uv run --with-editable ../../../cli --env-file .env gk eval validate --adapter eval_adapter.py:create_evaluator --suite eval-suite`: validate a local recorded-video eval suite
- `uv run --with-editable ../../../cli --env-file .env gk eval run --adapter eval_adapter.py:create_evaluator --suite eval-suite`: run a local recorded-video eval suite
- `uv add <package>`: add a package
