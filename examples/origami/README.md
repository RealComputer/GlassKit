# Example: Origami Guide (Rokid Glasses/Overshoot)

This app turns Rokid Glasses into a origami guide. The HUD shows folding reference images, and the backend proactively checks each fold with Overshoot.

For demo purpose, this app contains a browser demo page. That page simulates what the wearer sees through the glasses, with app controls.

It uses [Overshoot](https://overshoot.ai/) for live visual understanding.

## What The App Does

- Shows visual reference for each origami folding step on the Rokid HUD
- Automatically check the origami state and automatically proceeds every 0.5s. The check is done by Overshoot, combining actual scene frame with a reference image merged into a single image for confirm if the step is confirmed.
- Control:
  - Supports swipe forward/back for manual step navigation
  - Uses double tap to reset back to the start screen
- Lets the browser demo control the app (toggle automatic checking on or off when auto check is enabled at backend startup)

## How It Works

- `Rokid -> Backend` WebRTC: one peer connection with camera video and a `session-events` data channel
- `Backend -> Overshoot` WebRTC: backend-originated composed reference video for the active step
- `Backend <-> Overshoot` WebSocket: boolean inference results and keepalive
- `Browser <-> Backend` WebRTC: composed demo video plus a `demo-events` data channel for controls

## Development

See also [AGENTS.md](./AGENTS.md).

### Requirements

- [Rokid Glasses + dev cable](../../docs/how-to-get-rokid-glasses.md)
- `adb` for Android
- `uv` for Python
- Overshoot API key (`OVERSHOOT_API_KEY`)

### Configuration

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

Optional backend overrides (you can also specify them inline when you run fastapi server):

- `ORIGAMI_AUTO_CHECK_ENABLED=false` to keep sessions and the browser demo running without opening Overshoot streams. When disabled at startup, auto check stays off.
- `ORIGAMI_DEBUG_SAVE_OVERSHOOT_COMPOSITES=true` to save timestamped Overshoot input previews once per second while guiding
- `OVERSHOOT_API_URL`
- `OVERSHOOT_MODEL`

### Run The Backend

```bash
cd backend
uv run --env-file .env fastapi dev src/main.py --host 0.0.0.0
```

Open the browser demo:

```text
http://<YOUR_BACKEND>:8000/demo
```

### Run The Glasses App

Connect Rokid Glasses to your computer using the dev cable, enable Wi-Fi via ADB (see below), then install and run the app via `adb`.

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

### Assets

- Rokid HUD step images: `rokid/app/src/main/res/drawable-nodpi/origami_step_*.png`
- Backend demo HUD step images: `backend/assets/step-imgs/origami_step_*.png`
- Backend reference images: `backend/assets/ref-imgs/*.jpg`
- Step config and per-step prompts: `backend/assets/origami_steps.json`

## Vision Path Comparison

This example uses Overshoot differently from [`../rokid-overshoot-openai-realtime`](../rokid-overshoot-openai-realtime/README.md).

In this origami app, the Rokid client never connects to Overshoot directly. The glasses publish camera video to the FastAPI backend, and the backend opens its own WebRTC stream to Overshoot. The backend composes the camera view with the active fold reference image, sends that composed stream to Overshoot, and uses the boolean results to drive the fixed origami workflow.

In the mocktail coach, the glasses stream camera video directly to Overshoot after the backend brokers setup. The backend manages Overshoot prompts and results, but it does not sit in the video path or compose frames.
