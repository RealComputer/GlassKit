# Project overview
Rokid Overshoot is a vision streaming demo for Rokid Glasses. The app streams live camera video to Overshoot and renders incoming inference text as a rolling monochrome HUD log.

# Technical architecture
- Android app (`rokid/`) creates a WebRTC offer and sends it to backend `/vision/session`.
- Backend (`backend/`) creates an Overshoot stream via `POST /streams` (`source.type="webrtc"`), returns Overshoot answer SDP, and manages stream lifecycle.
- Overshoot inference results arrive over Overshoot WebSocket, and backend relays result text to Android over `/vision/session/{session_id}/events`.

# Key files
## Android (`./rokid/`)
- `app/src/main/java/com/example/rokidovershoot/MainActivity.kt`: temple-tap start/stop controls and rolling result log UI.
- `app/src/main/java/com/example/rokidovershoot/OvershootSessionClient.kt`: WebRTC offer/answer flow and backend websocket handling.
- `app/src/main/res/layout/activity_main.xml`: monochrome HUD layout with auto-scrolling log.
- `app/build.gradle.kts`: `VISION_SESSION_URL` BuildConfig value from `rokid/local.properties`.

## Backend (`./backend/`)
- `main.py`: FastAPI signaling endpoints, Overshoot REST calls, keepalive loop, and websocket passthrough.
- `.env.example`: environment template (`OVERSHOOT_API_KEY`, optional `OVERSHOOT_API_URL`).
- `pyproject.toml`: backend dependencies and tooling.

# Configuration
- `rokid/local.properties`: must define `VISION_SESSION_URL` (backend `/vision/session` URL).
- `backend/.env`: must define `OVERSHOOT_API_KEY`.
- Optional backend override: `OVERSHOOT_API_URL` (defaults to `https://api.overshoot.ai/v0.2`).

# Commands
## Android (ALWAYS run after Android changes)
- `cd rokid && ./gradlew :app:assembleDebug`

## Backend (ALWAYS run after backend changes)
- `cd backend && uv run ty check && uv run ruff check --fix && uv run ruff format`

## Backend utilities
- `cd backend && uv sync`
- `cd backend && uv run --env-file .env fastapi dev main.py --host 0.0.0.0`
- `cd backend && uv run -- python -c "print('hello')"`
- `cd backend && uv add <package>`

# Git Commit Guidelines
- Start message with "overshoot: "
