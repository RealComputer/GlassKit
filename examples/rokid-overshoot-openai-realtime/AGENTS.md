# Project Overview

This project is a server-authoritative mocktail coach for Rokid Glasses. The glasses stream camera video to Overshoot for live vision inference, receive spoken guidance from OpenAI Realtime API, and render a minimal HUD driven by the backend.

- Rokid Glasses are Android-based smart glasses with a camera, monochrome HUD, mic, and speaker.
- Overshoot is a Vision Language Model inference API for live video.

# Implementation Contracts

## Client contract

- The Android client must own only HUD rendering, gesture input, runtime permission handling, and the two WebRTC links.
- The Android client must not choose recipes, interpret vision results, advance workflow steps, or decide what speech to play.
- The Android client must render only the latest transcript and must clear stale transcript text when `speech_epoch` changes.

## Backend contract

- The FastAPI backend must remain authoritative for session lifecycle, phases, recipe loading, prompt switching, step progression, HUD state, and exact speech decisions.
- The backend must serialize per-session workflow through one session event loop.
- Recipe selection must happen only after the inventory scan stabilizes, using detected ingredient names and recipe filenames.

## External service contract

- Overshoot must provide structured outputs for the active prompt; the backend decides what those outputs mean.
- OpenAI Realtime must only do two things in this app: choose a recipe from filename ids and speak exact backend-provided lines.
- OpenAI Realtime must not invent workflow decisions or drive step transitions.

# Architecture

## Connection graph

- `Rokid <-> Backend` (WebSocket): persistent control channel for session lifecycle, HUD updates, and debug gestures.
- `Rokid -> Backend` (HTTP): setup path for both media links. The glasses send SDP offers to the backend, and the backend returns the answers for the Overshoot and OpenAI Realtime sessions.
- `Rokid <-> Overshoot` (WebRTC video): direct camera stream for live vision after backend setup.
- `Backend -> Overshoot` (HTTP): stream creation and prompt updates. The backend creates and manages the stream lifecycle through the Overshoot HTTP API.
- `Backend <-> Overshoot` (WebSocket): live inference result delivery plus keepalive traffic for the active stream.
- `Rokid <-> OpenAI Realtime` (WebRTC audio + data): direct audio playback and transcript delivery after backend setup.
- `Backend <-> OpenAI Realtime` (WebSocket sideband): server-side control for recipe selection and exact speech playback. The backend handles tools and can cancel or replace speech when server decisions change.

## End-to-end session flow

1. App launch: once camera permission is available, Rokid opens the backend control websocket and gets a server-created `session_id`.
2. User tap: Rokid sends `session.start` on the control socket.
3. Media setup:
   - Rokid sends the vision SDP offer to `/session/{session_id}/vision`
   - Rokid sends the realtime SDP offer to `/session/{session_id}/realtime`
4. Stream ownership:
   - Backend creates the Overshoot stream and starts the Overshoot websocket + keepalive tasks
   - Backend creates the OpenAI realtime call and opens the sideband websocket
5. Inventory scan:
   - Backend waits until both links are ready
   - Backend keeps the hardcoded inventory detector prompt active on Overshoot
   - Backend waits for two consecutive identical normalized ingredient arrays
6. Recipe selection:
   - Backend asks OpenAI Realtime to choose a recipe from filename ids using `list_recipes` and `activate_recipe`
   - Backend loads the chosen recipe JSON and switches to the first guided step
7. Guided workflow:
   - Backend patches the active Overshoot prompt for each step
   - Backend evaluates structured results and decides whether to advance, correct, or speak progress
   - Backend sends `hud.state` updates to Rokid and exact speech instructions to OpenAI sideband
8. Speech delivery:
   - OpenAI Realtime speaks to Rokid over WebRTC
   - Rokid renders only the latest transcript, keyed by `speech_epoch`

# Key Files

## Rokid (`./rokid/`)

- `app/src/main/java/com/example/rokidovershootopenairealtime/MainActivity.kt`: start/stop flow, gesture handling, HUD rendering, transcript reset on `speech_epoch`.
- `app/src/main/java/com/example/rokidovershootopenairealtime/BackendControlClient.kt`: backend control WebSocket and `hud.state` parsing.
- `app/src/main/java/com/example/rokidovershootopenairealtime/OvershootSessionClient.kt`: camera -> Overshoot WebRTC brokered through the backend.
- `app/src/main/java/com/example/rokidovershootopenairealtime/OpenAIRealtimeClient.kt`: receive-only OpenAI Realtime WebRTC audio plus transcript delta parsing.
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
- `uv run --env-file .env fastapi dev main.py --host 0.0.0.0`: start server with env loaded
- `uv run --env-file .env foo.py`: run a script with env loaded
- `uv run -- python -c "print('hello')"`: run a one-off Python command (the direct `python` command without uv might not be available.)
- `uv add <package>`: add a package

# Commit Guidelines

- Start message with "example/mocktail: "
