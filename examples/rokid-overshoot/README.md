# Example: Rokid Overshoot

This example app streams live camera video from Rokid Glasses to Overshoot and displays live inference text on the glasses HUD.

## What It Does

- Tap the temple area to start streaming.
- Tap the temple area again to stop.
- While running, inference result text is appended to the bottom of the screen and auto-scrolls.
- Old log lines are trimmed automatically.
- Starting a new run clears the previous log.

## Architecture

- Android app (`rokid/`)
  - Captures camera video.
  - Creates a local WebRTC offer.
  - Sends the offer to the backend `/vision/session` endpoint.
  - Applies the returned Overshoot answer SDP.
  - Opens the backend WebSocket `/vision/session/{session_id}/events` and renders incoming result text.
- Backend (`backend/`)
  - Calls Overshoot `POST /streams` with `source.type="webrtc"` and Android SDP.
  - Returns Overshoot answer SDP to Android.
  - Connects to the Overshoot WebSocket (`/ws/streams/{stream_id}`), authenticates with the API key, and relays result text to the Android WebSocket.
  - Maintains stream keepalive and closes streams on stop/disconnect.

Also see [AGENTS.md](./AGENTS.md) for details.

## Requirements

- Rokid Glasses + dev cable
- Android Studio with `adb`
- Python 3.12 with `uv`
- Overshoot API key (`OVERSHOOT_API_KEY`)

## Setup

Set the backend URL in `rokid/local.properties`:

```properties
VISION_SESSION_URL=http://<YOUR_BACKEND>/vision/session
```

Create the backend environment file:

```bash
cd backend
cp .env.example .env
# Set OVERSHOOT_API_KEY
```

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
