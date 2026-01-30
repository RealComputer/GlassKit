Backend service for the Rokid real-time assistant. It brokers WebRTC sessions, runs RF-DETR inference on incoming video, and feeds the latest annotated frame into the OpenAI Realtime conversation.

## Endpoints
- `POST /session`: SDP broker for the OpenAI Realtime (audio) session.
- `POST /vision/session`: SDP broker for the inbound vision WebRTC stream.

## Environment
Required:
- `OPENAI_API_KEY`
- `ROBOFLOW_API_KEY`

Optional vision overrides:
- `RFDETR_MODEL_ID`, `RFDETR_CONFIDENCE`, `RFDETR_MIN_INTERVAL_S`
- `RFDETR_FRAME_DIR`, `RFDETR_HISTORY_LIMIT`, `RFDETR_JPEG_QUALITY`

## Common commands
```sh
uv sync # install dependencies
cp .env.example .env # create env file

# run server with env loaded
uv run --env-file .env fastapi dev main.py --host 0.0.0.0

# type check, lint, and format
uv run ty check && uv run ruff check --fix && uv run ruff format
```
