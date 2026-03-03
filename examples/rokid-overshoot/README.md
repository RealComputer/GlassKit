# Example: Rokid Overshoot

This example app streams camera video from Rokid Glasses to Overshoot and displays live inference text on the glasses HUD.

## What It Does
- Press `ENTER` to start streaming.
- Press `ENTER` again to stop.
- While running, inference result text is appended to the bottom of the screen and auto-scrolls.
- Old log lines are trimmed automatically.
- Starting a new run clears the previous log.

## Architecture
- Android app (`rokid/`)
  - Captures camera video.
  - Creates a local WebRTC offer.
  - Sends the offer to backend `/vision/session`.
  - Applies the returned Overshoot answer SDP.
  - Opens backend websocket `/vision/session/{session_id}/events` and renders incoming result text.
- Backend (`backend/`)
  - Calls Overshoot `POST /streams` with `source.type="webrtc"` and Android SDP.
  - Returns Overshoot answer SDP to Android.
  - Connects to Overshoot websocket (`/ws/streams/{stream_id}`), authenticates with API key, and relays result text to Android websocket.
  - Maintains stream keepalive and closes streams on stop/disconnect.

## Requirements
- Rokid Glasses + dev cable
- Android Studio with `adb`
- Python 3.12 with `uv`
- Overshoot API key (`OVERSHOOT_API_KEY`)

## Configuration
Set Android backend URL in `rokid/local.properties`:

```properties
VISION_SESSION_URL=http://<YOUR_BACKEND>/vision/session
```

Create backend env file:

```bash
cd backend
cp .env.example .env
# set OVERSHOOT_API_KEY
```

Optional backend override:
- `OVERSHOOT_API_URL` (default: `https://api.overshoot.ai/v0.2`)

## Run Backend
```bash
cd backend
uv sync
uv run --env-file .env fastapi dev main.py --host 0.0.0.0
```

## Run Glasses App
Connect Rokid Glasses to your computer, enable Wi-Fi, then run the Android app from `rokid/` via Android Studio.

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
adb tcpip 5555
adb connect <IP>
adb devices
```

## Dev Workflow
See [AGENTS.md](./AGENTS.md) for required post-change checks.
