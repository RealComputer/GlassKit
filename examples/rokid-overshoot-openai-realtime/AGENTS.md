# Overview

This project is a server-authoritative mocktail coach for Rokid Glasses. The glasses stream camera video to Overshoot for live vision inference, receive spoken guidance from OpenAI Realtime, and render a minimal HUD driven by the backend.

- The Android app is intentionally thin: it owns the HUD, gestures, and the two WebRTC links.
- The FastAPI backend owns the full workflow state machine, recipe loading, Overshoot prompt switching, and OpenAI sideband control.
- Recipe selection happens after a hardcoded inventory scan, using detected ingredient names and recipe filenames.

# Architecture

- Android opens a backend control WebSocket at `/session/control`, receives a backend-generated `session_id`, and renders `hud.state` updates.
- Tap starts a run; the app then opens:
  - `/session/{session_id}/vision` for Overshoot WebRTC video streaming
  - `/session/{session_id}/realtime` for OpenAI Realtime WebRTC audio output and transcript events
- Backend session orchestration lives in `backend/session_manager.py`:
  - hardcoded inventory scan first
  - recipe selection via OpenAI sideband tool calls (`list_recipes`, `activate_recipe`)
  - step engine with prompt switching on the active Overshoot stream
  - speech epoch handling so only the newest transcript stays visible on-device
- Overshoot runs in clip mode with hardcoded processing settings:
  - `target_fps = 6`
  - `clip_length_seconds = 0.5`
  - `delay_seconds = 0.5`
- Overshoot prompt changes use `PATCH /streams/{stream_id}/config/prompt`; the output schema is fixed at stream creation time.

# Key files

## Rokid (`./rokid/`)

- `app/src/main/java/com/example/rokidovershoot/MainActivity.kt`: start/stop flow, gesture handling, HUD rendering, transcript reset on `speech_epoch`.
- `app/src/main/java/com/example/rokidovershoot/BackendControlClient.kt`: backend control WebSocket and `hud.state` parsing.
- `app/src/main/java/com/example/rokidovershoot/OvershootSessionClient.kt`: camera -> Overshoot WebRTC brokered through the backend.
- `app/src/main/java/com/example/rokidovershoot/OpenAIRealtimeClient.kt`: receive-only OpenAI Realtime WebRTC audio plus transcript delta parsing.
- `app/src/main/res/layout/activity_main.xml`: minimal start screen and running HUD.
- `app/build.gradle.kts`: `BACKEND_BASE_URL` BuildConfig value from `rokid/local.properties`.

## Backend (`./backend/`)

- `main.py`: FastAPI lifecycle and the control / vision / realtime routes.
- `session_manager.py`: small composition layer that wires the session mixins and shared clients together.
- `session_workflow.py`: workflow state machine, recipe activation, step evaluation, and HUD publishing.
- `session_runtime.py`: Overshoot/OpenAI runtime creation, sideband transport, keepalive, and speech/event sending.
- `recipe_catalog.py`, `session_types.py`, `session_constants.py`, `session_helpers.py`: recipe schemas, session dataclasses, shared constants, and pure helpers used by the orchestrator.
- `recipes/*.json`: data-driven workflow definitions. Filename keywords matter for recipe selection.
- `.env.example`: required keys and optional model overrides.

# Configuration

- `rokid/local.properties`: must define `BACKEND_BASE_URL` (for example `http://<HOST>:8000`).
- `backend/.env`: must define:
  - `OVERSHOOT_API_KEY`
  - `OPENAI_API_KEY`
- Optional backend overrides:
  - `OVERSHOOT_API_URL`
  - `OVERSHOOT_MODEL`
  - `OPENAI_REALTIME_MODEL`

# Gestures

- `KeyEvent.KEYCODE_ENTER`: tap, used to start or stop the run
- `KeyEvent.KEYCODE_DPAD_UP`: swipe forward, advances one internal debug step
- `KeyEvent.KEYCODE_DPAD_DOWN`: swipe backward, moves back one internal debug step

# Commands

## Rokid

`cd rokid` then:

- `./gradlew :app:assembleDebug`: ALWAYS run after Android changes

## Backend

`cd backend` then:

- `uv run ty check && uv run ruff check --fix && uv run ruff format`: ALWAYS run after backend changes
- `uv run --env-file .env fastapi dev main.py --host 0.0.0.0`: start the backend
- `uv run --env-file .env foo.py`: run a script with env loaded
- `uv run -- python -c "print('hello')"`: run a one-off Python command
- `uv add <package>`: add a package

# Commit Guidelines

- Start message with `example/mocktail: `
