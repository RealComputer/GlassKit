# Example: Rokid Glasses x OpenAI Realtime API x RF-DETR object detection

Real-time, vision-enabled voice assistant demo for Rokid Glasses that adds backend RF-DETR object detection. The glasses stream microphone audio to the OpenAI Realtime API over WebRTC and send camera video to the backend for detection. The backend injects the latest annotated frame into the conversation and handles tool calls.

This project is derived from [rokid-openai-realtime](../rokid-openai-realtime/README.md) for more specialized vision understanding and accuracy. If your use case can rely on the OpenAI Realtime API alone, use that example instead.

Feel free to modify and experiment with it!

<FIXME: I'll insert a demo video here later.>

## Features
- End-to-end example: Rokid Glasses + OpenAI Realtime API with RF-DETR detection.
- Real-time audio streaming with assistant speech playback.
- Camera stream processed by RF-DETR, annotated, then injected to OpenAI Realtime API.
- Sideband WebSocket with tool calls enabled.

## Architecture
- Android app (`rokid/`): two WebRTC sessions (audio to `/session`, video to `/vision/session`), temple button toggles start/stop.
- Backend (`backend/`): FastAPI broker for both sessions, RF-DETR inference loop, latest annotated frame store, OpenAI sideband WebSocket.

See [AGENTS.md](./AGENTS.md) for dev workflow.

## Requirements
- Rokid Glasses + dev cable
- Android Studio with `adb`
- Python 3.12 with `uv`
- OpenAI API key (`OPENAI_API_KEY`)
- Roboflow API key (`ROBOFLOW_API_KEY`)

## Configuration
Fill out `rokid/local.properties`:
```
SESSION_URL=http://<YOUR_BACKEND>/session
VISION_SESSION_URL=http://<YOUR_BACKEND>/vision/session
```

Create the backend env file:
```
cd backend
cp .env.example .env
# set OPENAI_API_KEY and ROBOFLOW_API_KEY in .env
```

Backend overrides: `RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`, `RFDETR_MIN_INTERVAL_S`, `RFDETR_JPEG_QUALITY`, `RFDETR_HISTORY_LIMIT`, `RFDETR_FRAME_DIR`.

Annotated frames are saved to `backend/frames` (`latest.jpg` plus a rolling history). Use the overrides above to tune retention and output location.

## Customize instruction items
Reference files:
- Instruction data: `backend/items/` (each `.txt` filename becomes an item name).
- Example instructions: `backend/items/ikea-wooden-box.txt`.
- System prompt: `backend/main.py` (`SESSION_INSTRUCTIONS`).
- Label map: `backend/vision.py` (`LABEL_MAP`).

## Run the backend
```
cd backend
uv sync
uv run --env-file .env fastapi dev main.py --host 0.0.0.0
```

## Run the glasses app
Before running the app, connect the Rokid Glasses to your computer using the dev cable, then turn on Wi-Fi on the glasses.

```sh
adb devices # check that you see your device
adb shell cmd wifi status # see whether it's connected; if not, follow the commands below
adb shell cmd wifi set-wifi-enabled enabled
adb shell 'cmd wifi connect-network "NAME" wpa2 "PASSWORD"'
adb shell cmd wifi status # confirm the connection

# Optional:
adb shell ip -f inet addr show wlan0 # check the glasses' IP
ping -c 5 -W 3 <IP> # check connectivity: first ping may time out
adb tcpip 5555 # prepare for remote adb connection for convenience
adb connect <IP> # connect to the glasses via remote adb
adb devices # check the remote connection (you can unplug the cable afterward for convenience)
```

Then, open the `rokid/` directory in Android Studio, select Rokid Glasses as the device, and run the app.

## How to prepare the model
For your scenario, fine-tune an object detection model. RF-DETR training walkthrough: https://www.youtube.com/watch?v=-OvpdLAElFA

1. Record example footage without the app using the standard Rokid Glasses video recording feature.
2. Use that footage to train the model.
3. Set `RFDETR_MODEL_ID` to your model and update `LABEL_MAP` in `backend/vision.py` so detected class names match your instruction part names.

## Roadmap
- Enable Wi-Fi from the glasses app so no manual `adb` is necessary.

## Related Examples
- [Rokid Glasses x OpenAI Realtime API](../rokid-openai-realtime/README.md): Base example for projects that can rely on the OpenAI Realtime API alone. This project builds on it to add specialized vision understanding and higher accuracy via RF-DETR.
- [Rokid Glasses x Object Detection](../rokid-rfdetr/README.md): Vision-only speedrun HUD with RF-DETR detection and split timing.
