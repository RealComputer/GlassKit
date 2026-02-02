# Rokid OpenAI Realtime + RF-DETR vision

Real-time voice assistant for Rokid Glasses with backend vision. The Android app sends audio to OpenAI Realtime over WebRTC and streams low-rate camera video to the backend for RF-DETR detection. The backend injects the latest annotated frame into the OpenAI conversation and handles tool calls.

## Architecture
- Android app (`rokid/`): two WebRTC sessions (audio to `/session`, video to `/vision/session`), temple button toggles start/stop.
- Backend (`backend/`): FastAPI broker for both sessions, RF-DETR inference loop, latest-frame store, OpenAI sideband WebSocket.

## Requirements
- Rokid Glasses + dev cable
- Android Studio + ADB
- Python 3.11+ with `uv`
- OpenAI API key (`OPENAI_API_KEY`)
- Roboflow API key (`ROBOFLOW_API_KEY`)

## Configuration
Create `rokid/local.properties` (gitignored):
```
SESSION_URL=http://<YOUR_BACKEND>:3000/session
VISION_SESSION_URL=http://<YOUR_BACKEND>:3000/vision/session
```

Create the backend env file:
```
cd backend
cp .env.example .env
# set OPENAI_API_KEY and ROBOFLOW_API_KEY in .env
```

Optional backend overrides:
`RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`, `RFDETR_MIN_INTERVAL_S`, `RFDETR_FRAME_DIR`, `RFDETR_HISTORY_LIMIT`, `RFDETR_JPEG_QUALITY`.

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
- `rokid/`: Android app (audio + vision WebRTC clients).
- `backend/`: FastAPI broker + RF-DETR inference.
- `AGENTS.md`: dev workflow notes (build/test expectations).
