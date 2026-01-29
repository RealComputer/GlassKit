# Project overview
Real-time, vision-enabled voice assistant example for Rokid Glasses (smart glasses). The Android client streams microphone audio to the OpenAI Realtime API (via the backend) and streams low-rate camera video over a separate WebRTC session to the backend for RF-DETR object detection. The backend injects the latest annotated frame into OpenAI responses and handles tool calls for assembly instructions.

# Technical architecture
- Android app (`rokid/`) runs two WebRTC sessions: audio to OpenAI Realtime via `/session`, and video to the backend via `/vision/session`.
- Backend (`backend/`) exposes FastAPI endpoints that broker SDP for both sessions, runs RF-DETR inference on incoming video, stores the latest annotated frame, and pushes it into the OpenAI Realtime conversation over a sideband WebSocket.
- Tooling flow: OpenAI tool calls `list_items`/`load_item_instructions` read `backend/items/*.txt` to drive step-by-step assembly guidance.

# Key files
Android
- `rokid/app/src/main/java/com/example/rokidopenairealtimerfdetr/MainActivity.kt`: permissions, start/stop, conversation UI, keypress toggle.
- `rokid/app/src/main/java/com/example/rokidopenairealtimerfdetr/OpenAIRealtimeClient.kt`: WebRTC audio session, data channel event parsing.
- `rokid/app/src/main/java/com/example/rokidopenairealtimerfdetr/BackendVisionClient.kt`: WebRTC camera capture + low-FPS video stream.
- `rokid/app/build.gradle.kts`: BuildConfig for `SESSION_URL` and `VISION_SESSION_URL` sourced from `rokid/local.properties`.

Backend
- `backend/main.py`: FastAPI app, `/session` and `/vision/session`, sideband WebSocket to OpenAI, tool call dispatch.
- `backend/vision.py`: RF-DETR inference, annotation, `LatestFrameStore`, frame saving.
- `backend/items/*.txt`: assembly instruction content for tools.
- `backend/.env.example`: env template for required keys.
- `backend/inference-sample.py`: standalone RF-DETR test stub.

# Configuration
- `rokid/local.properties`: must set `SESSION_URL` and `VISION_SESSION_URL` (backend `/session` and `/vision/session`).
- `backend/.env`: must set `OPENAI_API_KEY` and `ROBOFLOW_API_KEY`.
- Optional backend overrides: `RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`, `RFDETR_MIN_INTERVAL_S`, `RFDETR_FRAME_DIR`, `RFDETR_HISTORY_LIMIT`, `RFDETR_JPEG_QUALITY`.

# Commands agents should know
Android (required after Android changes)
- `cd rokid && ./gradlew :app:assembleDebug`

Backend (required after backend changes)
- `cd backend && uv run ty check && uv run ruff check --fix && uv run ruff format`

Backend dev run
- `cd backend && cp .env.example .env`
- `cd backend && uv run --env-file .env fastapi dev main.py --host 0.0.0.0`

Backend utilities
- `cd backend && uv run --env-file .env inference-sample.py`
- `cd backend && uv run -- python -c "print('hello')"`
- `cd backend && uv add <package>`
