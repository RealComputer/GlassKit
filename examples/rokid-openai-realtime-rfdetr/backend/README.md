```sh
cp .env.example .env # set ROBOFLOW_API_KEY and OPENAI_API_KEY

# run server with env loaded
uv run --env-file .env fastapi dev main.py --host 0.0.0.0

# endpoints
# - POST /session        -> OpenAI Realtime (audio)
# - POST /vision/session -> WebRTC video ingest for RF-DETR

# optional vision env overrides
# - RFDETR_MODEL_ID, RFDETR_CONFIDENCE, RFDETR_MIN_INTERVAL_S
# - RFDETR_FRAME_DIR, RFDETR_HISTORY_LIMIT, RFDETR_JPEG_QUALITY

# type check, lint, and format
uv run ty check && uv run ruff check --fix && uv run ruff format

# use Python like this:
uv run -- python foo.py

# you can add package like this:
uv add package_name
```
