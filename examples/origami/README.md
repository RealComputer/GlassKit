# Origami Guide for Rokid Glasses

This example turns Rokid Glasses into a silent origami guide. The HUD shows one of seven folding reference images, the glasses stream camera video to the backend, and the backend proactively checks each fold with Overshoot. After two consecutive `true` checks, the backend shows `Done!` for two seconds and advances to the next step.

The backend also serves a browser demo at `/demo`. That page receives a composed WebRTC video feed with a backend-rendered green HUD overlaid on the camera POV, and its buttons send the same control events as the glasses gestures.

## What The App Does

- Starts from `Double tap temple to start`
- Shows `Origami Guide`, `Step N/7`, and the provided step image on the Rokid HUD
- Captures camera at `1024x768@15fps` and adapts outbound WebRTC to `5fps`
- Lets the backend perform Overshoot checks every `0.5s`
- Supports swipe forward/back for manual step navigation
- Uses tap to toggle automatic checking on or off
- Uses double tap to reset back to the start screen

## How It Works

- `Rokid -> Backend` WebRTC: one peer connection with camera video and a `session-events` data channel
- `Backend -> Overshoot` WebRTC: backend-originated composed reference video for the active step
- `Backend <-> Overshoot` WebSocket: boolean inference results and keepalive
- `Browser <-> Backend` WebRTC: composed demo video plus a `demo-events` data channel for controls

## Requirements

- [Rokid Glasses + dev cable](../../docs/how-to-get-rokid-glasses.md)
- Android Studio with `adb`
- Python 3.12 with `uv`
- Overshoot API key (`OVERSHOOT_API_KEY`)

## Configuration

Set the backend URL in `rokid/local.properties`:

```properties
BACKEND_BASE_URL=http://<YOUR_BACKEND>:8000
```

Create the backend env file:

```bash
cd backend
cp .env.example .env
# set OVERSHOOT_API_KEY
```

Optional backend overrides:

- `ORIGAMI_OVERSHOOT_ENABLED=false` to keep sessions and the browser demo running without opening Overshoot streams
- `OVERSHOOT_API_URL`
- `OVERSHOOT_MODEL`

You can also toggle Overshoot at runtime. Turning it back on requires `OVERSHOOT_API_KEY` to be configured.

```bash
curl -X POST http://<YOUR_BACKEND>:8000/debug/overshoot \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

## Run The Backend

```bash
cd backend
uv run --env-file .env fastapi dev main.py --host 0.0.0.0
```

Open the browser demo:

```text
http://<YOUR_BACKEND>:8000/demo
```

## Run The Glasses App

Connect Rokid Glasses to your computer using the dev cable, enable Wi-Fi via ADB, then run the Android app from `rokid/` in Android Studio.

Useful ADB commands:

```bash
adb devices
adb shell cmd wifi status
adb shell cmd wifi set-wifi-enabled enabled
adb shell 'cmd wifi connect-network "NAME" wpa2 "PASSWORD"'
adb shell cmd wifi status
```

Optional wireless ADB:

```bash
adb shell ip -f inet addr show wlan0
ping -c 5 -W 3 <IP>
adb tcpip 5555
adb connect <IP>
adb devices
```

## Assets

- Rokid HUD step images: `rokid/app/src/main/res/drawable-nodpi/origami_step_*.png`
- Backend demo HUD step images: `backend/assets/step-imgs/origami_step_*.png`
- Backend reference images: `backend/assets/ref-imgs/*.jpg`
- Step config and per-step prompts: `backend/assets/origami_steps.json`

## Developer Checks

Backend:

```bash
cd backend
uv run ty check && uv run ruff check --fix && uv run ruff format
```

Android:

```bash
cd rokid
./gradlew :app:assembleDebug
```
