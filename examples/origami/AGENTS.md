# Project Overview

This project is a server-authoritative origami guide for Rokid Glasses. The glasses show a visual folding guide on the HUD, stream camera video to the backend, and receive backend-driven state updates over a WebRTC data channel. The backend checks each fold with Overshoot and drives the fixed origami workflow.

- Rokid Glasses are Android-based smart glasses with a camera, monochrome HUD, and temple touchpad.
- Overshoot is a vision-language model inference API for live video.

# Runtime Architecture

- The Android client stays thin: it renders the HUD, handles camera permission and touchpad gestures, publishes camera video through `/session/media`, and sends gesture commands over `session-events`.
- The FastAPI backend owns the single active device session, current step, HUD state, manual and automatic progression, auto-check availability, and Overshoot runtime.
- The backend composes camera frames with the active reference image, opens its own WebRTC stream to Overshoot, updates prompts and stream state over HTTP, and receives fold-check results over WebSocket.
- Overshoot results and manual navigation both flow through the backend session loop, so the backend remains the only place that advances steps.
- Turning auto check off stops Overshoot while keeping the device and browser media sessions alive. `ORIGAMI_AUTO_CHECK_ENABLED=false` disables Overshoot stream creation for the whole backend process.
- Browser `/demo` connects through `/demo/session`, receives the composed camera/HUD video feed, and sends controls over `demo-events`.

# Key Files

## Rokid (`./rokid/`)

- `app/src/main/java/com/example/origamiguide/MainActivity.kt`: start screen, touchpad gesture mapping, and HUD rendering.
- `app/src/main/java/com/example/origamiguide/OrigamiSessionClient.kt`: camera WebRTC publishing and `session-events` data channel.
- `app/src/main/res/layout/activity_main.xml`: monochrome Rokid HUD.
- `app/src/main/res/drawable-nodpi/origami_step_*.png`: seven step guide images.
- `app/build.gradle.kts`: `BACKEND_BASE_URL` BuildConfig value from `rokid/local.properties`.

## Backend (`./backend/`)

- `src/main.py`: FastAPI lifecycle and `/session/media`, `/demo`, and `/demo/session` routes.
- `src/session_manager.py`: public session manager, session loop, HUD state, and origami workflow state machine.
- `src/overshoot_runtime.py`: Overshoot stream lifecycle, prompt updates, WebSocket results, keepalive, and stats logging.
- `src/rtc_media.py`: aiortc peer connection helpers and backend-originated video tracks.
- `src/rendering.py`: Overshoot reference composition, browser demo composition, and HUD image rendering.
- `src/session_state.py`: session data classes and latest-frame buffer.
- `src/origami_config.py`: step config loader.
- `assets/origami_steps.json`: seven step definitions and prompts.
- `assets/step-imgs/*.png`: green browser-demo HUD versions of the step guide images.
- `assets/ref-imgs/*.jpg`: active step reference images used for Overshoot composition.
- `.env.example`: required key and optional Overshoot overrides.

# Touchpad Controls

- `KeyEvent.KEYCODE_BACK` / Android back callback: Rokid double tap. Starts from the initial screen and resets while running or completed.
- `KeyEvent.KEYCODE_ENTER`: tap. Consumed by the app and intentionally has no workflow action.
- `KeyEvent.KEYCODE_DPAD_DOWN`: swipe forward. Advances one step manually.
- `KeyEvent.KEYCODE_DPAD_UP`: swipe backward. Moves one step back manually.

# Commands

## Rokid

`cd rokid` then:

- `./gradlew :app:assembleDebug`: Always run after Android changes

## Backend

`cd backend` then:

- `uv run ty check && uv run ruff check --fix && uv run ruff format`: Always run after backend changes
- `uv run --env-file .env fastapi dev src/main.py --host 0.0.0.0`: start server with env loaded
- `uv add <package>`: add a package
