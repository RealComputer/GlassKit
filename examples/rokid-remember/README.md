# Example: Rokid Glasses Long Recorder

This example project is a long-duration recorder app for Rokid Glasses.

## Features
- Records either:
  - `video` mode: camera video + microphone audio (`.mp4`)
  - `audio` mode: microphone only (`.m4a`)
- 10-minute automatic segmentation to keep file sizes manageable.
- Automatic upload of completed segments to backend.
- Failed uploads are retried; local files are kept until upload succeeds.
- Minimal in-glasses UI while recording.

## Controls
- `DPAD_UP`: select `video` mode (when idle)
- `DPAD_DOWN`: select `audio` mode (when idle)
- `ENTER`: start recording
- `ENTER` while recording: stop recording

## Segment naming
Uploaded files are saved as:
- `<start_unix>-<end_unix>.mp4` (video)
- `<start_unix>-<end_unix>.m4a` (audio)

## Architecture
- Android app (`rokid/`):
  - `MainActivity`: key controls + readiness checks
  - `RecordingService`: foreground recording service, 10-minute rotation, upload retry
- Backend (`backend/`):
  - `GET /health` returns `{ "status": "ok" }`
  - `POST /upload` accepts multipart upload and saves to disk

## Requirements
- Rokid Glasses + dev cable
- Android Studio with `adb`
- Python 3.12 with `uv`

## Configuration
Fill out `rokid/local.properties`:
```
BACKEND_BASE_URL=http://<YOUR_BACKEND>:8000
```

Legacy fallback is also supported:
```
VISION_SESSION_URL=http://<YOUR_BACKEND>:8000/vision/session
```
(when this is set, the app derives `BACKEND_BASE_URL` automatically)

Backend optional env file:
```
cd backend
cp .env.example .env
# optionally set UPLOAD_DIR
```

## Run backend
```
cd backend
uv sync
uv run --env-file .env fastapi dev main.py --host 0.0.0.0
```

## Run the glasses app
```sh
adb devices
adb shell cmd wifi status

# if needed (manual Wi-Fi setup)
adb shell cmd wifi set-wifi-enabled enabled
adb shell 'cmd wifi connect-network "NAME" wpa2 "PASSWORD"'

# build/install from Android Studio or CLI
cd rokid
./gradlew :app:assembleDebug
```

## API contract
### `GET /health`
Response:
```json
{ "status": "ok" }
```

### `POST /upload`
`multipart/form-data` fields:
- `file`: binary segment file
- `mode`: `video` or `audio`
- `start_unix`: segment start unix time (seconds)
- `end_unix`: segment end unix time (seconds)

Response:
```json
{ "status": "ok", "filename": "1700000000-1700000600.mp4" }
```
