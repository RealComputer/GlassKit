Backend service for a vision-driven speedrun HUD. It brokers a WebRTC video stream from the glasses, runs RF-DETR inference on the latest frame, saves annotated frames, and advances speedrun splits based on detections. State updates are sent over a WebRTC data channel.

## Endpoints
- `POST /vision/session`: SDP broker for the inbound vision WebRTC stream (video + data channel).

## Environment
Required:
- `ROBOFLOW_API_KEY`

Optional vision overrides:
- `RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`
- `RFDETR_FRAME_DIR`, `RFDETR_HISTORY_LIMIT`, `RFDETR_JPEG_QUALITY`

Speedrun config:
- `speedrun_config.json` in this directory defines the speedrun name, groups/splits, and the detection class for completion.

## Common commands
```sh
uv sync # install dependencies
cp .env.example .env # create env file

# run server with env loaded
uv run --env-file .env fastapi dev main.py --host 0.0.0.0

# type check, lint, and format
uv run ty check && uv run ruff check --fix && uv run ruff format
```
