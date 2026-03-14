# Example: Mocktail Coach for Rokid Glasses (Overshoot x OpenAI Realtime API)

This example turns Rokid Glasses into a guided mocktail coach. The glasses stream camera video to [Overshoot](https://overshoot.ai/) for live scene understanding, receive spoken instructions from OpenAI Realtime, and render a minimal HUD showing the current recipe task and latest transcript only.

## What it does

- Shows a simple start screen: `Mocktail Coach` and `Look at the ingredients and tap to start`
- Runs a hardcoded inventory scan first
- Chooses the most likely recipe from recipe filenames
- Loads that recipe JSON on the backend
- Guides the user step by step with spoken instructions and HUD task highlighting
- Supports debug step navigation from Rokid swipe gestures

## Architecture

- Android app:
  - control WebSocket to the backend
  - WebRTC video stream to Overshoot through the backend
  - WebRTC audio output and transcript events from OpenAI Realtime through the backend SDP broker
- Backend:
  - authoritative per-session workflow engine
  - recipe loading from `backend/recipes/`
  - Overshoot prompt switching on the active stream
  - OpenAI Realtime sideband for recipe-selection tool calls and exact speech playback

## Requirements

- Rokid Glasses + dev cable
- Android Studio with `adb`
- Python 3.12 with `uv`
- Overshoot API key (`OVERSHOOT_API_KEY`)
- OpenAI API key (`OPENAI_API_KEY`)

## Configuration

Set the backend URL in `rokid/local.properties`:

```properties
BACKEND_BASE_URL=http://<YOUR_BACKEND>
```

Create the backend env file:

```bash
cd backend
cp .env.example .env
# set OVERSHOOT_API_KEY and OPENAI_API_KEY
```

Optional backend overrides:

- `OVERSHOOT_API_URL`
- `OVERSHOOT_MODEL`
- `OPENAI_REALTIME_MODEL`

## Gestures

- Tap: `KeyEvent.KEYCODE_ENTER`
- Swipe forward: `KeyEvent.KEYCODE_DPAD_UP`
- Swipe backward: `KeyEvent.KEYCODE_DPAD_DOWN`

## Run backend

```bash
cd backend
uv run --env-file .env fastapi dev main.py --host 0.0.0.0
```

## Run glasses app

Connect Rokid Glasses to your computer using the dev cable, enable Wi-Fi on the glasses, then run the Android app from `rokid/` in Android Studio.

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

## Recipe files

- Recipes live in `backend/recipes/`
- Filename keywords are used during recipe selection, so keep ingredient names in the filename
- The current example recipe is `orange-juice-blue-gatorade-lime-mocktail.json`

See [AGENTS.md](./AGENTS.md) for development workflow and architecture notes.
