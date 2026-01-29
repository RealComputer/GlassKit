Project overview: Real-time, vision-enabled voice assistant example for Rokid Glasses (smart glasses). The Android client streams microphone audio to the OpenAI Realtime API, and streams low-rate camera video over a separate WebRTC session to the backend for RF-DETR object detection; the backend injects the latest annotated frame into OpenAI responses. Our backend establishes the OpenAI connection, ingests video, and handles function calls.

# Rokid Glasses (Android) app — `rokid/`

- Entry point `MainActivity`: auto-starts streaming after camera/mic permissions; temple tap (`KEYCODE_DPAD_CENTER`/`ENTER`) toggles start/stop.
- Media: `OpenAIRealtimeClient` streams audio to OpenAI; `BackendVisionClient` streams video to `/vision/session`.
- After Android code changes, always run `cd rokid && ./gradlew :app:assembleDebug`.

# Backend — `backend/`

- Required env: `OPENAI_API_KEY`, `ROBOFLOW_API_KEY`
- After backend code changes, always run `cd backend && uv run ty check && uv run ruff check --fix && uv run ruff format`.
- Setup (for human):


```sh
cp .env.example .env # set ROBOFLOW_API_KEY and OPENAI_API_KEY

# run server with env loaded
uv run --env-file .env fastapi dev main.py --host 0.0.0.0

# type check, lint, and format
uv run ty check && uv run ruff check --fix && uv run ruff format

# use Python command like this:
uv run -- python -c "print('hello')"

# you can add package like this:
uv add package_name
```
