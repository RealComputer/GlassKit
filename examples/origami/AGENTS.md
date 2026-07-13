# Project Overview

This project is a server-authoritative origami guide for Rokid Glasses. The glasses show a visual folding guide on the HUD, stream camera video to the backend, and receive backend-driven state updates over a WebRTC data channel. The backend checks each fold with a VLM hosted through Overshoot and drives the fixed origami workflow.

- Rokid Glasses are Android-based smart glasses with a camera, monochrome HUD, and temple touchpad.
- Overshoot is a vision-language model inference API for live video.

# Architecture

- The Android client stays thin: it renders the HUD, handles camera permission, and maps touchpad gestures into backend commands.
- The FastAPI backend owns the active session, current step, HUD state, manual and automatic progression, auto-check availability, and fold-check runtime.
- Overshoot only sees backend-composed video, not a direct Rokid stream.
- Browser `/demo` is a backend-connected viewer/controller. It approximates the wearer's view by reconstructing the Rokid HUD over the latest camera frame, but it is not a separate workflow owner.
- Turning auto check off stops the fold-check runtime and closes any provider stream while keeping the device and browser media sessions alive. `ORIGAMI_AUTO_CHECK_ENABLED=false` disables provider stream creation for the whole backend process.
- The Overshoot API uses LiveKit publishing plus explicit chat-completion prompts. The backend creates an Overshoot stream, publishes backend-composed camera/reference video into the returned LiveKit room, polls stream readiness until the first frame is ingested, and then calls `/chat/completions` sequentially with `ovs://streams/<id>?frame_index=-1` image references.
- The backend records the real camera frames sent into the fold-check path before reference-image composition by default. Recordings are written under `backend/debug/fold-check-inputs` unless `ORIGAMI_FOLD_CHECK_INPUT_RECORDING_DIR` overrides the location, and `ORIGAMI_RECORD_FOLD_CHECK_INPUTS=false` disables this recording.

## Connection Graph

- `Rokid <-> Backend` WebRTC: camera video upstream plus `session-events` commands and HUD state.
- `Backend -> Overshoot` LiveKit/WebRTC: composed fold-check video.
- `Backend -> Overshoot` HTTP: stream setup, stream status polling, keepalive, chat-completion fold checks, and stream deletion.
- `Browser <-> Backend` WebRTC: demo video plus `demo-events` controls.

## Session Flow

1. Rokid shows the start screen.
2. Double tap opens a backend media session and starts the origami workflow.
3. The backend enters the first step, publishes HUD state, and starts fold checking when auto check is available.
4. The backend sends composed camera/reference video to the Overshoot LiveKit room.
5. The backend prompts the hosted VLM against the latest ingested stream frame, parses the boolean response, and decides whether to advance the step.
6. Swipe controls send manual navigation commands to the backend, and browser demo controls can start, navigate, toggle auto check, and reset the active workflow.
7. Completion leaves the HUD on the completed workflow screen until a reset returns it to the start screen.

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
- `src/fold_check_runtime.py`: session-scoped fold-check orchestration, worker tasks, LiveKit reconnect recovery, prompt gating, and runtime cleanup.
- `src/overshoot_client.py`: Overshoot HTTP API client for stream setup/status, keepalive, shared chat-completion requests, retries, and response parsing.
- `src/fold_check_prompts.py`: hard-coded VLM chat wrapper prompts and message construction used by live checks and recorded-video evals.
- `src/overshoot_livekit.py`: LiveKit publisher setup, token refresh, track options, and image-to-video-frame capture helpers.
- `src/fold_check_diagnostics.py`: fold-check debug composite saving and pre-composition input recording lifecycle.
- `src/fold_check.py`: shared fold-check helpers for reference composition, image reference encoding, step/reference loading, and boolean result parsing.
- `src/rtc_media.py`: aiortc peer connection helpers and backend-originated video tracks.
- `src/recording.py`: non-blocking video recording for pre-composition fold-check input frames.
- `src/rendering.py`: fold-check reference composition, browser demo composition, and HUD image rendering.
- `src/session_state.py`: session data classes, latest-frame buffer, and grouped fold-check runtime state.
- `src/origami_config.py`: step config loader.
- `eval/adapter.py`: recorded-video `glasskit eval` adapter that sends each composed sampled frame through the shared fold-check/Overshoot chat-completion path without LiveKit. It deliberately implements individual `evaluate` calls so `glasskit eval run --concurrency N` can overlap independent requests.
- `eval/check_image.py`: Gemini-backed helper for checking individual camera images against a target step with the case generator's labeling path.
- `eval/generate_case.py`: Gemini-backed helper for turning a small label plan into an initial recorded-video eval case YAML.
- `eval/suggest_criteria.py`: high-thinking Gemini helper for proposing generalizable step criteria from the target reference, neighboring references, and balanced reviewed true/false frames.
- `eval/test_generate_case.py`: regression coverage for full-case overwrite and selected-target update behavior.
- `eval/test_suggest_criteria.py`: regression coverage for criteria example selection, ignored-sample handling, and output validation.
- `assets/origami_steps.json`: seven step definitions and fold-check criteria.
- `assets/step-imgs/*.png`: backend demo copies of the step guide images, colorized into the green HUD style at render time.
- `assets/ref-imgs/*.jpg`: active step reference images used for fold-check composition.
- `.env.example`: required key and optional Overshoot overrides.

# Commands

## Rokid

`cd rokid` then:

- `./gradlew :app:assembleDebug`: Always run after Android changes

## Backend

`cd backend` then:

- `uv run ty check && uv run ruff check --fix && uv run ruff format`: Always run after backend changes
- `uv run --env-file .env fastapi dev src/main.py --host 0.0.0.0`: start server with env loaded
- `uv run --with-editable ../../../cli --env-file .env glasskit eval run --concurrency 2`: run a local recorded-video eval suite with this repo's current CLI checkout and bounded parallel Overshoot requests
- `uv add <package>`: add a package
