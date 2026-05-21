# Example: Proactive Drink-making Coach (Rokid Glasses/Overshoot/OpenAI Realtime API)

This example turns Rokid Glasses into a proactive drink-making assistant. The glasses look at the ingredients, choose a recipe, show the current step, and guide you based on what they see in real time. The goal is an interaction that feels more like a helpful person beside you than a voice assistant waiting for prompts.

It uses [Overshoot](https://overshoot.ai/) for live visual understanding and the OpenAI Realtime API for low-latency spoken guidance and transcript streaming.

[demo.webm](https://github.com/user-attachments/assets/f11631f9-6ce2-4524-9634-4b4746f64fab)

## What the app does

- Scans the visible ingredients at the start
- Chooses the best matching recipe automatically
- Watches the table as you work and reacts step by step
- Guides you step by step with short spoken instructions
- Shows the current task and the latest guidance transcript on the display
- Corrects you if you're not following the recipe
- (Supports debug step navigation from swipe controls.)

## How it works

At a high level:

- Rokid Glasses stream live camera video into Overshoot for scene understanding
- The FastAPI backend is authoritative for recipe choice, workflow state, step transitions, HUD state, and speech timing
- The backend creates and controls an OpenAI Realtime session for live LLM recipe selection and spoken guidance
- OpenAI Realtime speaks the backend's lines over WebRTC and streams transcript text back to the HUD
- The Android app stays thin: it renders the HUD, handles gestures, and owns the media connections

Detailed technical architecture, workflow contracts, configuration, and developer workflow live in [AGENTS.md](./AGENTS.md).

## Requirements

- [Rokid Glasses + dev cable](../../docs/how-to-get-rokid-glasses.md)
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
- The current example recipe is `orange-juice-blue-gatorade-lime-mocktail.json`

## Related projects

- [rokid-overshoot](../rokid-overshoot/README.md): Minimal Overshoot-only example for streaming camera video to Overshoot and rendering live inference text on the HUD.
- [rokid-openai-realtime](../rokid-openai-realtime/README.md): Simple OpenAI Realtime API assistant example for Rokid Glasses with real-time audio/video streaming and voice responses.
