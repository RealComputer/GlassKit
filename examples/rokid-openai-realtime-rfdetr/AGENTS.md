Project overview: Real-time, vision-enabled voice assistant example for Rokid Glasses (smart glasses). The Android client (running on the glasses) directly streams microphone audio and a camera feed over WebRTC to the OpenAI Realtime API, then speaks back to the user. Our backend establishes the connection and handles function calls.

# Rokid Glasses (Android) app — `rokid/`

- Entry point `MainActivity`: auto-starts streaming after camera/mic permissions; temple tap (`KEYCODE_DPAD_CENTER`/`ENTER`) toggles start/stop.
- Media: `OpenAIRealtimeClient` uses Stream WebRTC.
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
