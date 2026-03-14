# Example: Mocktail Coach for Rokid Glasses

This example turns Rokid Glasses into a guided mocktail-making assistant. It uses [Overshoot](https://overshoot.ai/) for live visual understanding and the OpenAI Realtime API for low-latency spoken guidance and transcript streaming. You look at the ingredients on the table, tap once to start, and the glasses coach you through the drink with a minimal HUD and spoken instructions.

## What the app does

- Shows a simple start screen: `Mocktail Coach` and `Look at the ingredients and tap to start`
- Scans the visible ingredients first
- Chooses the best matching recipe automatically
- Watches the table as you work and reacts step by step
- Guides the user step by step with short spoken instructions
- Highlights the current task on the HUD and shows only the latest transcript
- Corrects you if you pick up the wrong bottle or stop at the wrong time
- Keeps the completed HUD visible at the end
- Supports debug step navigation from Rokid swipe gestures

## How it works

At a high level:

- Rokid Glasses stream live camera video into [Overshoot](https://overshoot.ai/) for scene understanding
- The FastAPI backend is authoritative for recipe choice, workflow state, step transitions, HUD state, and speech timing
- The backend creates and controls an OpenAI Realtime session for spoken guidance
- The OpenAI Realtime speaks the backend's exact lines over WebRTC and streams transcript text back to the HUD
- The Android app stays thin: it renders the HUD, handles gestures, and owns the media connections

Detailed technical architecture, workflow contracts, configuration, and developer workflow live in [AGENTS.md](./AGENTS.md).

## Requirements

- Rokid Glasses + dev cable
- Android Studio with `adb`
- Python 3.12 with `uv`
- Overshoot API key (`OVERSHOOT_API_KEY`)
- OpenAI API key (`OPENAI_API_KEY`)

## Developer Setup

### Configuration

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

## Run The Backend

```bash
cd backend
uv run --env-file .env fastapi dev main.py --host 0.0.0.0
```

## Run The Glasses App

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

See [AGENTS.md](./AGENTS.md) for the source-of-truth technical overview, architecture details, configuration contracts, and development workflow.
