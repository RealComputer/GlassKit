# Example: Rokid Glasses x Object Detection

This is an example Rokid Glasses app that uses object-detection models. Feel free to modify and experiment with it!

To demonstrate the template, this repo includes a vision-driven speedrun HUD for Rokid Glasses. You can run a speedrun in the real world, in your own scenario. A sushi speedrun is included for reference.

[demo.webm](https://github.com/user-attachments/assets/0dcaf9aa-35c7-49a4-971d-8ef7645715da)

## Features
- End-to-end example: glasses HUD + backend object-detection workflow.
- Global timer and split timing HUD.
- Configurable speedrun definitions (groups, splits, labels).
- Hands-free split detection in real time with automatic completion.
- Two-hit confirmation to reduce false detections.
- Annotated frame capture for inspection and model tuning.
- Manual split advance/back for testing and debugging.
- Controls:
  - Temple tap: start the run timer.
  - Temple swipe forward/backward: move to next/previous split (debugging).

## Architecture
- Android app (`rokid/`), running on the glasses: WebRTC video + data channel streaming to the backend, HUD rendering, touchpad controls.
- Backend (`backend/`): FastAPI HTTP API, WebRTC ingestion, fine-tuned RF-DETR (object detection model) inference loop, state management.

See [AGENTS.md](./AGENTS.md) for dev workflow.

## Requirements
- Rokid Glasses + dev cable
- Android Studio with `adb`
- Python 3.12 with `uv`
- Roboflow API key (`ROBOFLOW_API_KEY`) if you use Roboflow-hosted weights (see "How to prepare the model" for details and alternatives).

## Configuration
Fill out `rokid/local.properties`:
```
VISION_SESSION_URL=http://<YOUR_BACKEND>/vision/session
```

Create the backend env file:
```
cd backend
cp .env.example .env
# set ROBOFLOW_API_KEY
```

Speedrun configuration lives in `backend/speedrun_config.json` (name, groups/splits, object-detection class mapping).

Backend overrides: `RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`.

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

# Optional (wireless ADB):
adb shell ip -f inet addr show wlan0 # check the glasses' IP
ping -c 5 -W 3 <IP> # check connectivity: first ping may time out
adb tcpip 5555 # prepare for remote adb connection for convenience
adb connect <IP> # connect to the glasses via remote adb
adb devices # check the remote connection (you can unplug the cable afterward for convenience)
```

Then, open the `rokid/` directory in Android Studio, select Rokid Glasses as the device, and run the app.

## How to prepare the model
For each speedrun config, you need to fine-tune an object detection model. See https://www.youtube.com/watch?v=-OvpdLAElFA for RF-DETR training.

1. Record your example runs without the app using the standard Rokid Glasses video recording feature.
2. Use that footage to train the model.
3. Create a speedrun config file for your run.

This backend uses the `inference` library with Roboflow-hosted weights by default. `ROBOFLOW_API_KEY` is only used to download weights to the backend once; inference runs locally after download. To avoid relying on the Roboflow platform, train/export weights anywhere (for example, Colab) and switch the backend to the `rfdetr` library to load those weights directly, which removes the need for `ROBOFLOW_API_KEY`.

## Roadmap
- Enable Wi-Fi from the glasses app so no manual `adb` is necessary.
- On-device, offline work so no internet connection is needed.

## Related Examples
- [Rokid Glasses x OpenAI Realtime API](../rokid-openai-realtime/README.md): Vision-enabled voice assistant demo streaming audio/video over WebRTC to the OpenAI Realtime API with custom tool calls.
- [Rokid Glasses x OpenAI Realtime API x RF-DETR object detection](../rokid-openai-realtime-rfdetr/README.md): Similar to the project above, but adds object detection and injects annotated frames into the Realtime API conversation for better accuracy.
