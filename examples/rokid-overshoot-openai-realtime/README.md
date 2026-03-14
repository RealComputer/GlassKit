# Example: Mocktail Coach for Rokid Glasses

This example turns Rokid Glasses into a guided mocktail-making assistant. It uses [Overshoot](https://overshoot.ai/) for live visual understanding and the OpenAI Realtime API for low-latency spoken guidance and transcript streaming.

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

Connect Rokid Glasses to your computer using the dev cable, enable Wi-Fi via ADB (see below), then run the Android app from `rokid/` in Android Studio.

Useful ADB commands:

```bash
adb devices # confirm your device is visible
adb shell cmd wifi status # see whether it's connected; if not, follow the commands below
adb shell cmd wifi set-wifi-enabled enabled # enable Wi-Fi
adb shell 'cmd wifi connect-network "NAME" wpa2 "PASSWORD"' # set network
adb shell cmd wifi status # confirm the connection
```

Optional wireless ADB:

```bash
adb shell ip -f inet addr show wlan0 # check the glasses IP
ping -c 5 -W 3 <IP> # check connectivity (the first ping may time out)
adb tcpip 5555 # enable remote ADB mode
adb connect <IP> # connect to the glasses over remote ADB
adb devices # verify the remote connection (you can unplug the cable afterward)
```

## Recipe files

- Recipes live in `backend/recipes/`
- Filename keywords are used during recipe selection, so keep ingredient names in the filename
- The current example recipe is `orange-juice-blue-gatorade-lime-mocktail.json`
