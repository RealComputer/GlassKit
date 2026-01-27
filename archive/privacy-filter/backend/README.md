# Backend Services

Real-time privacy infrastructure for video streaming applications.

## Overview

Two core services work together to provide privacy-preserving video processing:

- **Privacy Filter**: Real-time video processor with face anonymization, consent detection, and transcription
- **Control API** (optional): REST API for consent management and system control

## Prerequisites

- Python 3.12
- `uv` package manager
- FFmpeg
- MediaMTX streaming server

## Quick Start

### 1. Install dependencies

```bash
# Install Python dependencies
uv sync
```

### 2. Download models

```bash
# Face detection model
wget -P ./filter https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

# Face recognition library is installed via pip (face_recognition)
# No model download needed - uses dlib's pre-trained models

# LLM for consent detection
hf download lmstudio-community/Phi-3.1-mini-4k-instruct-GGUF Phi-3.1-mini-4k-instruct-Q4_K_M.gguf --local-dir ./filter
```

### 3. Start services

```bash
# Terminal 1: MediaMTX server
mediamtx

# Terminal 2: Privacy filter
uv run filter/main.py

# Terminal 3: Control API (optional)
uv run fastapi dev api/main.py

# Terminal 4: Send test stream
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -f flv rtmp://127.0.0.1:1935/live/stream

# Terminal 5: View filtered output
ffplay -loglevel error rtsp://127.0.0.1:8554/filtered
```

## Configuration

Several configurations are available. Can be adjusted for your use case and performance tuning.

See `./filter/misc/config.py`.

## Development

```bash
# Type checking
uv run basedpyright

# Linting & formatting
uv run ruff check --fix && uv run ruff format

# Run tests (when available)
uv run pytest
```

## Control API

REST API for managing the privacy filter system.

### Endpoints

```
GET    /consents            # List all consented individuals
GET    /consents/{id}/image # Get consent face image
DELETE /consents/{id}       # Revoke consent
```
