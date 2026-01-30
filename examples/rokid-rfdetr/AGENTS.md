# Project overview
Vision-driven speedrun HUD for Rokid Glasses (Android smart glasses). The Android client streams camera video to the backend over WebRTC and receives split/state updates over a data channel. The backend runs RF-DETR object detection, advances splits with a two-hit confirmation rule, and saves annotated frames for inspection.

# Technical architecture
- Android app (`rokid/`) runs a single WebRTC session to `/vision/session` for video + data channel messaging.
- Backend (`backend/`) exposes FastAPI `/vision/session`, runs RF-DETR inference on the latest frame, maintains speedrun state, and publishes config/state/split events over the data channel.

# Key files
## Android (`./rokid/`)
- `MainActivity.kt`: HUD rendering, timer management, DPAD controls.
- `BackendVisionClient.kt`: WebRTC camera capture + data channel messaging.
- `SpeedrunModels.kt`: config/state data classes.
- `build.gradle.kts`: BuildConfig for `VISION_SESSION_URL` sourced from `rokid/local.properties`.

## Backend (`./backend/`)
- `main.py`: FastAPI app, `/vision/session`, data channel handling.
- `vision.py`: RF-DETR inference loop, annotated frame saving.
- `speedrun.py`: speedrun config loader + state machine.
- `speedrun_config.json`: groups/splits and detection class mapping.
- `.env.example`: env template for required keys.

# Configuration
- `rokid/local.properties`: must set `VISION_SESSION_URL` (backend `/vision/session`).
- `backend/.env`: must set `ROBOFLOW_API_KEY`.
- Optional backend overrides: `RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`, `RFDETR_FRAME_DIR`, `RFDETR_HISTORY_LIMIT`, `RFDETR_JPEG_QUALITY`.

# Commands
## Android (always run after Android changes)
- `cd rokid && ./gradlew :app:assembleDebug`

## Backend (always run after backend changes)
- `cd backend && uv run ty check && uv run ruff check --fix && uv run ruff format`

## Backend utilities
- `cd backend && uv run --env-file .env foo.py` (run a script with env loaded)
- `cd backend && uv run -- python -c "print('hello')"` (run a one-off Python command)
- `cd backend && uv add <package>` (add a package)
