# Rokid RF-DETR speedrun HUD

Vision-driven speedrun HUD for Rokid Glasses. The Android app streams camera video to the backend over WebRTC and receives split/state updates over a data channel. The backend runs RF-DETR object detection, advances splits with a two-hit confirmation rule, and saves annotated frames for inspection. The HUD is monochrome, so UI styling relies on typography instead of color.

## Architecture
- Android app (`rokid/`): WebRTC video + data channel, HUD rendering, DPAD controls.
- Backend (`backend/`): FastAPI `/vision/session`, RF-DETR inference loop, speedrun state machine.

## Requirements
- Rokid Glasses + dev cable
- Android Studio + ADB
- Python 3.11+ with `uv`
- Roboflow API key (`ROBOFLOW_API_KEY`)

## Configuration
Create `rokid/local.properties` (gitignored):
```
VISION_SESSION_URL=http://<YOUR_BACKEND>:3000/vision/session
```

Create the backend env file:
```
cd backend
cp .env.example .env
# set ROBOFLOW_API_KEY in .env
```

Speedrun configuration lives in `backend/speedrun_config.json` (name, groups/splits, class mapping).

Optional backend overrides:
`RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`, `RFDETR_FRAME_DIR`, `RFDETR_HISTORY_LIMIT`, `RFDETR_JPEG_QUALITY`.

## Run the backend
```
cd backend
uv sync
uv run --env-file .env fastapi dev main.py --host 0.0.0.0
```

## Run the glasses app
1. Open `rokid/` in Android Studio and select the Rokid Glasses device.
2. Build the APK: `./gradlew :app:assembleDebug`
3. Run from Android Studio.

## Controls
- Temple button (Enter): start/stop the run timer.
- DPAD up/down: move to next/previous split (debugging).

## Rokid device setup (one-time)
Connect the glasses over USB first, then enable Wi-Fi:
```
adb devices
adb shell cmd wifi status
adb shell cmd wifi set-wifi-enabled enabled
adb shell cmd wifi connect-network <NAME> wpa2 <PASSWORD>
adb shell cmd wifi status
```

Optional remote ADB over Wi-Fi:
```
adb shell ip -f inet addr show wlan0
adb tcpip 5555
adb connect <IP>
adb devices
```

## Project layout
- `rokid/`: Android app (video + data channel client).
- `backend/`: FastAPI broker + RF-DETR inference + speedrun state.
- `AGENTS.md`: dev workflow notes (build/test expectations).
