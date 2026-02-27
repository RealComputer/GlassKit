# Project overview
Long-duration recorder for Rokid Glasses. The app records either video+audio or audio-only, splits recordings into 10-minute segments, uploads completed segments to the backend, and retries failed uploads without deleting local files until upload succeeds.

# Technical architecture
- Android app (`rokid/`) uses a foreground service for recording continuity and uploads completed segments to the backend.
- Backend (`backend/`) exposes `GET /health` and `POST /upload`, and saves uploaded files to disk.

# Key files
## Android (`./rokid/`)
- `MainActivity.kt`: minimal HUD, network/health readiness checks, key controls.
- `RecordingService.kt`: segmented recording, foreground notification, upload retry loop.
- `BackendApiClient.kt`: `/health` and `/upload` HTTP client.
- `RecorderMode.kt`: recording mode enum.
- `build.gradle.kts`: BuildConfig for `BACKEND_BASE_URL` sourced from `rokid/local.properties`.

## Backend (`./backend/`)
- `main.py`: FastAPI app with `/health` and `/upload`.
- `.env.example`: optional `UPLOAD_DIR` override.

# Configuration
- `rokid/local.properties`: set `BACKEND_BASE_URL` (legacy `VISION_SESSION_URL` is still accepted and converted).
- `backend/.env`: optional `UPLOAD_DIR`.

# Commands
## Android (ALWAYS run after Android changes)
- `cd rokid && ./gradlew :app:assembleDebug`

## Backend (ALWAYS run after backend changes)
- `cd backend && uv run ty check && uv run ruff check --fix && uv run ruff format`

## Backend utilities
- `cd backend && uv sync`
- `cd backend && uv run --env-file .env fastapi dev main.py --host 0.0.0.0`
