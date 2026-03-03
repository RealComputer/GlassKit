# Overview

This project demonstrates Rokid Glasses using Overshoot. The Rokid Glasses app streams live camera feed to Overshoot and renders the responses to the display.

- Rokid Glassses is an Android-based smart glasses with camera, monochrome HUD, mic, and speaker.
- Overshoot is a Vison Language Model inference API for live video.

# Architecture

- Android app (`rokid/`) creates a WebRTC offer and sends it to backend.
- Backend (`backend/`) creates an Overshoot stream via an Overshoot API, returns Overshoot answer SDP, and manages stream lifecycle.
- Overshoot inference results arrive over Overshoot WebSocket, and backend relays result text to Android.

# Key files

## Rokid Glasses (`./rokid/`)

- `app/src/main/java/com/example/rokidovershoot/MainActivity.kt`: temple-tap start/stop controls and rolling result log UI.
- `app/src/main/java/com/example/rokidovershoot/OvershootSessionClient.kt`: WebRTC offer/answer flow and backend websocket handling.
- `app/src/main/res/layout/activity_main.xml`: monochrome HUD layout with auto-scrolling log.
- `app/build.gradle.kts`: `VISION_SESSION_URL` BuildConfig value from `rokid/local.properties`.

## Backend (`./backend/`)

- `main.py`: FastAPI signaling endpoints, Overshoot REST calls, keepalive loop, and websocket passthrough.
- `.env.example`: environment template (`OVERSHOOT_API_KEY`).
- `pyproject.toml`: backend dependencies and tooling.

# Configuration

- `rokid/local.properties`: must define `VISION_SESSION_URL` (backend `/vision/session` URL).
- `backend/.env`: must define `OVERSHOOT_API_KEY`.

# Commands

## Rokid

`cd rokid` then:

- `./gradlew :app:assembleDebug`: ALWAYS run after Android changes

## Backend

`cd backend` then:

- `uv run ty check && uv run ruff check --fix && uv run ruff format`: ALWAYS run after backend changes
- `uv run --env-file .env fastapi dev main.py --host 0.0.0.0`: start server with env loaded
- `uv run --env-file .env foo.py`: run a script with env loaded)
- `uv run -- python -c "print('hello')"`: run a one-off Python command (note that the direct `python` command without uv might not not available.)
- `uv add <package>`: add a package

# Commit Guidelines

- Start message with "overshoot: "
