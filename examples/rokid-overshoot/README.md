# Example: Rokid Overshoot

This example app streams live camera video from Rokid Glasses to [Overshoot](https://overshoot.ai/) and displays live inference text on the glasses HUD.

[demo.webm](https://github.com/user-attachments/assets/3f412e40-009d-402a-9c3b-a2a28d0a010b)

## What It Does

- Tap the temple area to start streaming.
- Tap the temple area again to stop.
- While running, you see live result text appear on the glasses display.
- New lines are added at the bottom and the view auto-scrolls.
- Each new run starts with a clean screen.

## Architecture

- The Android app captures camera video and starts a live session.
- The backend connects that session to Overshoot and handles stream lifecycle.
- Inference text is relayed back to the Android app and rendered on the glasses HUD in real time.

See [AGENTS.md](./AGENTS.md) for detailed flow and implementation notes.

For a more advanced version of this pattern, see [rokid-overshoot-openai-realtime](../rokid-overshoot-openai-realtime). It builds on the same Overshoot foundation and adds OpenAI Realtime for spoken guidance and a richer assistant workflow.

## Requirements

- Rokid Glasses + [dev cable](../../docs/how-to-get-rokid-glasses.md#rokid-glasses-dev-cable)
- Android Studio with `adb`
- Python 3.12 with `uv`
- Overshoot API key (`OVERSHOOT_API_KEY`)

## Setup

Set the backend URL in `rokid/local.properties`:

```properties
BACKEND_BASE_URL=http://<YOUR_BACKEND>
```

Create the backend environment file:

```bash
cd backend
cp .env.example .env
# Set OVERSHOOT_API_KEY
```

Optional backend overrides:

- `OVERSHOOT_API_URL`
- `OVERSHOOT_PROMPT`
- `OVERSHOOT_MODEL`
- `OVERSHOOT_PROCESSING_TARGET_FPS`
- `OVERSHOOT_PROCESSING_CLIP_LENGTH_SECONDS`
- `OVERSHOOT_PROCESSING_DELAY_SECONDS`

For current default values, see `backend/session_manager.py`.

## Run Backend

```bash
cd backend
uv run --env-file .env fastapi dev main.py --host 0.0.0.0
```

## Run Glasses App

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
