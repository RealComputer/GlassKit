# Project overview
Real-time, vision-enabled voice assistant example for Rokid Glasses (Android smart glasses). The Android client streams microphone audio to the OpenAI Realtime API WebRTC and streams camera video over a separate WebRTC to the backend for RF-DETR object detection. The backend injects the latest annotated frame into OpenAI responses and handles tool calls.

# Technical architecture
- Android app (`rokid/`) runs two WebRTC sessions: audio to OpenAI Realtime via `/session`, and video to the backend via `/vision/session`.
- Backend (`backend/`) exposes FastAPI endpoints that broker SDP for both sessions, pre-warms the RF-DETR model on startup, runs inference on incoming video, stores the latest annotated frame, and pushes it into the OpenAI Realtime conversation over a sideband WebSocket.

# Key files
## Android (`./rokid/`)
- `MainActivity.kt`: permissions, start/stop, conversation UI, keypress toggle.
- `OpenAIRealtimeClient.kt`: WebRTC audio session, data channel event parsing.
- `BackendVisionClient.kt`: WebRTC camera capture + video stream.
- `build.gradle.kts`: BuildConfig for `SESSION_URL` and `VISION_SESSION_URL` sourced from `rokid/local.properties`.

## Backend (`./backend/`)
- `main.py`: FastAPI app, `/session` and `/vision/session`, sideband WebSocket to OpenAI, tool call dispatch.
- `vision.py`: RF-DETR inference, annotation, `LatestFrameStore`, frame saving.
- `.env.example`: env template for required keys.

# Configuration
- `rokid/local.properties`: must set `SESSION_URL` and `VISION_SESSION_URL` (backend `/session` and `/vision/session`).
- `backend/.env`: must set `OPENAI_API_KEY` and `ROBOFLOW_API_KEY`.
- Optional backend overrides: `RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`, `RFDETR_MIN_INTERVAL_S`, `RFDETR_FRAME_DIR`, `RFDETR_HISTORY_LIMIT`, `RFDETR_JPEG_QUALITY`.

# Commands
## Android (always run after Android changes)
- `cd rokid && ./gradlew :app:assembleDebug`

## Backend (always run after backend changes)
- `cd backend && uv run ty check && uv run ruff check --fix && uv run ruff format`

## Backend utilities
- `cd backend && uv run --env-file .env foo.py` (run a script with env loaded)
- `cd backend && uv run -- python -c "print('hello')"` (run a one-off Python command)
- `cd backend && uv add <package>` (add a package)
