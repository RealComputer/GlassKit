# Overview

This project demonstrates Rokid Glasses integrated with Overshoot. The app streams a live camera feed to Overshoot and renders inference responses on the glasses display.

- Rokid Glasses are Android-based smart glasses with a camera, monochrome HUD, mic, and speaker.
- Overshoot is a Vision Language Model inference API for live video.

# Architecture

- User starts or stops streaming with a temple tap in the Android app (`rokid/`).
- Android captures camera video, creates a WebRTC offer, and sends signaling data to the backend (`backend/`).
- Backend creates and manages the Overshoot stream, then returns the answer SDP to Android.
- Android applies the answer and streams live media directly to Overshoot over WebRTC.
- Backend listens to Overshoot stream events and relays inference result text to Android over a backend WebSocket.
- Android app appends each result line to a rolling HUD log and auto-scrolls while the session is active.

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
- `uv run --env-file .env foo.py`: run a script with env loaded
- `uv run -- python -c "print('hello')"`: run a one-off Python command (the direct `python` command without uv might not be available.)
- `uv add <package>`: add a package

# Commit Guidelines

- Start message with "overshoot: "
