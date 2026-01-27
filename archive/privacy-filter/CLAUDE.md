# Real-time Video Privacy Infrastructure

## Project Overview

A privacy-preserving video processing system for smart glasses and similar devices. Provides real-time face anonymization with consent management, enabling privacy-compliant applications.

## Project Structure

- `./backend/filter/` - Real-time privacy filter implementation (Python)
- `./backend/api/` - Control API server (FastAPI)
- `./examples/rewind/` - Reference implementation and inspector UI (React/TypeScript)

## Development Guidelines

### Backend Python (`./backend/`)

Before committing, run quality checks:

```bash
# Type checking
uv run basedpyright

# Linting & formatting
uv run ruff check --fix && uv run ruff format
```

### 1. Privacy Filter (`./backend/filter/`)

Multi-threaded video processing pipeline with face anonymization and transcription:

**Features:**
- Receives RTMP input streams with video and audio
- Detects and anonymizes (blur or solid mask) faces using YuNet neural network
- Face recognition for consented users using face_recognition library
- Speech transcription using VAD and Faster Whisper
- Automatic consent detection from transcribed speech using local LLM Phi-3.5 Mini
- File-based consent management with real-time monitoring using watchfiles
- Automatic loading of existing consent files on startup
- Dynamic consent addition/revocation through file system changes
- Selective face anonymization - consented faces remain visible with name labels
- Outputs to RTSP
- MediaMTX exposes WebRTC stream for consumption and records video
- Multi-threaded architecture with queue-based communication
- Graceful shutdown and health monitoring

**Architecture:**
```
backend/
├─ shared/
│  └─ consent_file_utils.py # Shared consent file naming and parsing utilities
├─ filter/
├─ main.py                  # Entry point
├─ misc/
│  ├─ pipeline.py           # Pipeline orchestrator
│  ├─ config.py             # Configuration with env vars
│  ├─ types.py              # Shared data types
│  ├─ queues.py             # Bounded queues with backpressure
│  ├─ state.py              # Connection/thread state management
│  ├─ metrics.py            # Performance metrics
│  ├─ logging.py            # Structured logging
│  ├─ shutdown.py           # Signal handling
│  ├─ face_detector.py      # Face detection module
│  ├─ face_recognizer.py    # Face recognition module
│  ├─ consent_detector.py   # LLM-based consent detection
│  ├─ consent_capture.py    # Head image capture utility for consent
│  └─ consent_manager.py    # File-based consent management with monitoring
└─ threads/
    ├─ base.py              # Abstract base thread
    ├─ input.py             # RTMP demuxer thread
    ├─ video.py             # Face detection/recognition thread
    ├─ audio.py             # Audio transcoding thread
    ├─ vad.py               # Real-time VAD processing thread
    ├─ speech_worker.py     # Background Whisper transcription thread
    ├─ output.py            # RTSP muxer thread
    └─ monitor.py           # Health monitoring thread
```

**Threading Model:**
- **Input Thread**: Demuxes RTMP stream into video/audio queues
- **Video Thread**: Processes frames with face detection/recognition, selective anonymization, and consent captures
- **Audio Thread**: Transcodes audio to Opus for WebRTC
- **VAD Thread**: Real-time Voice Activity Detection (non-blocking)
- **Speech Worker Thread(s)**: Background Whisper transcription and consent detection
- **Output Thread**: Muxes processed streams to RTSP
- **Monitor Thread**: Health monitoring and metrics collection
- **Consent Monitor Thread**: Watches consent_captures/ directory for real-time file changes (runs via watchfiles)

**Transcription & Consent Detection:**
The transcription system uses a non-blocking architecture to prevent real-time degradation:
- VAD Thread continuously processes audio in real-time, detecting speech boundaries
- When speech ends, complete segments are queued for transcription
- Speech Worker Thread(s) consume segments and run Whisper inference in the background
- Transcribed text is analyzed by a local LLM to detect explicit consent phrases
- Consent detection identifies both the consent status and speaker's name when available
- This separation ensures VAD never waits for transcription, maintaining real-time performance

**Face Recognition & Consent Management:**
- When consent is detected via speech, the system captures a head image of the largest face (assumed to be the speaker)
- Head images are saved to `./consent_captures/` with format `YYYYMMDDHHMMSS_[name].jpg`
- On startup, all existing consent files are loaded and face features extracted
- File system monitoring via watchfiles detects real-time consent changes:
  - Adding a file grants consent for that person
  - Deleting a file revokes consent for that person
- Face features are extracted using face_recognition library (128-dimensional encodings) and stored in an in-memory database
- Multiple captures per person are supported for improved recognition accuracy
- In subsequent frames, all detected faces are matched against the consented faces database
- Recognized consented faces remain visible with green name labels displayed above them
- Unrecognized faces are anonymized (blurred or masked) for privacy protection

```bash
# Default: Gaussian blur
uv run filter/main.py

# Alternative: Solid ellipse masking (fits face shape)
FACE_ANONYMIZATION_MODE=solid_ellipse uv run filter/main.py
```

### 2. Control API (`./backend/api/`)

FastAPI-based REST API for consent management and system control:

**Endpoints:**
- `GET /consents` - List all consented individuals
- `GET /consents/{id}/image` - Retrieve consent face image
- `DELETE /consents/{id}` - Revoke consent for a person

**Running the API:**
```bash
uv run fastapi dev api/main.py
```

### 3. Example App (`./examples/rewind/`)

React/TypeScript application showcasing the privacy infrastructure:

- Real-time WHEP video streaming display
- Connection status monitoring
- Consent management UI integrated with Control API
  - View list of consented individuals with their face images
  - Display consent timestamp and person's name
  - Revoke consent with confirmation dialog
  - Auto-refresh consent list every 5 seconds
- Recording playback with MediaMTX integration
  - View list of available recordings with timestamps and duration
  - Play recordings in modal with full video controls
  - Delete recordings with confirmation
  - Auto-refresh recording list
- AI chat integration (planned)

Run these commands before committing changes:

```bash
# Build the application
npm run build

# Run linting
npm run lint
```

## Additional Notes

- Python commands use `uv run` (e.g., `uv run python script.py`)
