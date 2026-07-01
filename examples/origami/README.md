# Example: Origami Guide (Rokid Glasses/Overshoot)

This app turns Rokid Glasses into an origami guide. The HUD shows folding reference images, and the backend proactively checks each fold with Overshoot.

For demo purposes, the app includes a browser demo page that simulates what the wearer sees through the glasses and exposes app controls.

It uses [Overshoot](https://overshoot.ai/) for live visual understanding.

## What the App Does

- Shows a visual reference for each origami folding step on the Rokid HUD
- Checks the current fold with Overshoot and advances through the fixed workflow
- Controls:
  - Supports swipe forward/back for manual step navigation
  - Uses double tap to start from the start screen and reset while running or completed
- Lets the browser demo view the composed camera/HUD feed and send controls, including auto-check toggling when available

## Development

See also [AGENTS.md](./AGENTS.md) for technical details.

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

Optional backend overrides can also be specified inline when starting FastAPI:

- `ORIGAMI_AUTO_CHECK_ENABLED=false` to keep sessions and the browser demo running without opening Overshoot streams. When disabled at startup, auto check stays off.
- `ORIGAMI_RECORD_OVERSHOOT_INPUTS=false` to disable the default recording of real camera frames sent into the Overshoot path for inspection. Recordings are written under `backend/debug/overshoot-inputs` before reference-image composition.
- `ORIGAMI_OVERSHOOT_INPUT_RECORDING_DIR` to choose where Overshoot input recordings are written
- `ORIGAMI_DEBUG_SAVE_OVERSHOOT_COMPOSITES=true` to save Overshoot input previews for debugging
- `ORIGAMI_DEBUG_OVERSHOOT_COMPOSITE_DIR` to choose where debug preview images are written
- `OVERSHOOT_API_URL`
- `OVERSHOOT_MODEL`

### Run the Backend

```bash
cd backend
uv run --env-file .env fastapi dev src/main.py --host 0.0.0.0
```

Open the browser demo:

```text
http://<YOUR_BACKEND>:8000/demo
```

### Run the Glasses App

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

In this origami app, the Rokid client never connects to Overshoot directly. The glasses publish camera video to the FastAPI backend, and the backend opens its own WebRTC stream to Overshoot. The backend composes the camera view with the active fold reference image, sends that composed stream to Overshoot, and uses the results to drive the fixed origami workflow.

In the mocktail coach, the glasses stream camera video directly to Overshoot after the backend brokers setup. The backend manages Overshoot prompts and results, but it does not sit in the video path or compose frames.
