# Project Overview

This project is a server-authoritative origami guide for Rokid Glasses. The glasses show a seven-step folding HUD, stream camera video to the backend, and receive backend-driven state updates over a WebRTC data channel. The backend checks the active fold with Overshoot and advances after two consecutive `true` results.

- Rokid Glasses are Android-based smart glasses with a camera, monochrome HUD, and temple touchpad.
- Overshoot is a Vision Language Model inference API for live video.

# Implementation Contracts

## Client Contract

- The Android client owns only HUD rendering, gesture input, runtime permission handling, and the WebRTC media/data-channel connection.
- The Android client must not interpret Overshoot results or decide automatic step progression.
- The Android client sends gesture commands over the `session-events` data channel:
  - `session.start`
  - `session.reset`
  - `manual.next`
  - `manual.prev`
- The Android camera must capture at `1024x768@15fps`, adapt outbound WebRTC to `5fps`, and keep explicit LAN-oriented bitrate settings while a media session is active.
- The Android app must hold wake and Wi-Fi low-latency/high-performance locks only during the active WebRTC media session.

## Backend Contract

- The FastAPI backend remains authoritative for session lifecycle, current step, automatic checking, step progression, prompt selection, Overshoot runtime state, and HUD state.
- The backend serializes each device session through one session event loop.
- A step passes only after two consecutive Overshoot boolean `true` results; any `false` resets the streak.
- Manual next/previous controls cancel a pending `Done!` delay and update the active step without recreating Overshoot when auto check remains on.
- While guiding, step changes should keep the existing Overshoot stream alive and patch `/streams/{stream_id}/config/prompt` when the step prompt changes.
- During the two-second `Done!` phase, incoming Overshoot results are ignored; the stream may remain connected until the next step prompt/reference is active.
- Turning auto check off stops the Overshoot runtime while keeping the device/browser media session alive.
- `ORIGAMI_AUTO_CHECK_ENABLED=false` must keep device/browser media alive while preventing Overshoot stream creation; this startup setting is not toggleable at runtime.
- `ORIGAMI_DEBUG_SAVE_OVERSHOOT_COMPOSITES=true` must save timestamped Overshoot input preview JPEGs under a gitignored debug directory without requiring an active Overshoot stream.
- Backend-originated H.264 streams to Overshoot and the browser demo use a LAN-oriented aiortc target/cap while preserving aiortc's native low bitrate floor for congestion recovery.

## External Service Contract

- Overshoot receives backend-composed camera frames with the active step reference header.
- Overshoot uses the active step prompt from `backend/assets/origami_steps.json`.
- The default prompt is: `Return true if the origami model on the tray matches the reference shape; otherwise, return false.`
- The Overshoot output schema is `{"type":"boolean"}`.

# Architecture

## Connection Graph

- `Rokid -> Backend` (WebRTC): one peer connection with camera video and `session-events` data channel.
- `Backend -> Overshoot` (WebRTC): backend-originated video stream containing camera POV plus the active reference image.
- `Backend -> Overshoot` (HTTP): stream creation, prompt patching, keepalive, and stream deletion.
- `Backend <-> Overshoot` (WebSocket): boolean inference results.
- `Browser <-> Backend` (WebRTC): browser demo receives a composed camera/HUD video feed and sends controls over `demo-events`.

## End-to-End Session Flow

1. App launch: Rokid renders the start screen: `Double tap temple to start`.
2. Double tap: Rokid creates `/session/media` with camera video and the `session-events` data channel.
3. Backend creates a fresh single-device session and answers the WebRTC offer.
4. Rokid opens `session-events` and queues `session.start`.
5. Backend enters step 1, publishes `hud.state`, and starts an Overshoot stream for the active step.
6. Backend samples camera frames, overlays the active reference image header, and publishes that video to Overshoot.
7. Overshoot results arrive over WebSocket. Two consecutive `true` values mark the step done.
8. Backend publishes `Done!`, ignores Overshoot results for two seconds, then advances to the next step without reconnecting the stream.
9. Swipe forward/back sends manual step navigation.
10. At completion, double tap sends `session.reset` and returns the HUD to the initial screen.
11. Browser `/demo` can connect at any time and receives the latest camera/HUD composite plus matching control buttons, including automatic-check toggling.

# Key Files

## Rokid (`./rokid/`)

- `app/src/main/java/com/example/origamiguide/MainActivity.kt`: start screen, touchpad gesture mapping, and HUD rendering.
- `app/src/main/java/com/example/origamiguide/OrigamiSessionClient.kt`: camera WebRTC publishing and `session-events` data channel.
- `app/src/main/res/layout/activity_main.xml`: monochrome Rokid HUD.
- `app/src/main/assets/origami_steps_svg/origami_step_*.svg`: smooth SVG source versions of the seven step guide images.
- `app/src/main/res/drawable-anydpi/origami_step_*.xml`: Android vector drawables used by the Rokid HUD for the seven step guide images.
- `app/src/main/res/drawable-nodpi/origami_step_*.png`: original seven step guide PNGs retained as raster references.
- `app/build.gradle.kts`: `BACKEND_BASE_URL` BuildConfig value from `rokid/local.properties`.

## Backend (`./backend/`)

- `main.py`: FastAPI lifecycle and `/session/media`, `/demo`, and `/demo/session` routes.
- `session_manager.py`: session loop, aiortc media ingest, Overshoot bridge, boolean result handling, HUD state, and browser demo composition.
- `origami_config.py`: step config loader.
- `assets/origami_steps.json`: seven step definitions and prompts.
- `assets/step-imgs/*.png`: green browser-demo HUD versions of the step guide images.
- `assets/ref-imgs/*.jpg`: active step reference images used for Overshoot composition.
- `.env.example`: required key and optional Overshoot overrides.

# Configuration

- `rokid/local.properties`: must define `BACKEND_BASE_URL` (for example `http://<HOST>:8000`).
- `backend/.env`: must define:
  - `OVERSHOOT_API_KEY`
- Optional backend overrides:
  - `ORIGAMI_AUTO_CHECK_ENABLED`
  - `OVERSHOOT_API_URL`
  - `OVERSHOOT_MODEL`

# Gestures

- `KeyEvent.KEYCODE_BACK` / Android back callback: Rokid double tap. Starts from the initial screen, resets after completion.
- `KeyEvent.KEYCODE_ENTER`: tap. Consumed by the app and intentionally has no workflow action.
- `KeyEvent.KEYCODE_DPAD_DOWN`: swipe forward. Advances one step manually.
- `KeyEvent.KEYCODE_DPAD_UP`: swipe backward. Moves one step back manually.

# Commands

## Rokid

`cd rokid` then:

- `./gradlew :app:assembleDebug`: ALWAYS run after Android changes

## Backend

`cd backend` then:

- `uv run ty check && uv run ruff check --fix && uv run ruff format`: ALWAYS run after backend changes
- `uv run --env-file .env fastapi dev main.py --host 0.0.0.0`: start server with env loaded
- `uv run --env-file .env foo.py`: run a script with env loaded
- `uv run -- python -c "print('hello')"`: run a one-off Python command. The direct `python` command without uv might not be available.
- `uv add <package>`: add a package
