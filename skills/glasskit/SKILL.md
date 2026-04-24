---
name: glasskit
description: Use when building, modifying, or debugging GlassKit smart-glasses apps for Rokid Glasses, including Android monochrome HUDs, touchpad or voice controls, camera/mic/speaker access, WebRTC streaming, OpenAI Realtime, Overshoot vision, RF-DETR/object detection, or backend-orchestrated proactive workflows. Includes a portable Rokid hello-world starter and focused implementation references.
---

# GlassKit

GlassKit is a dev suite for smart-glasses apps. This skill currently targets Rokid Glasses and packages the patterns that are easy to miss when building through a general Android or backend workflow.

## Workflow

1. For a new Rokid app, copy `assets/rokid-hello-world/` into the target workspace first. Rename the package/application id after copying.
2. Identify the requested feature area and read only the matching reference below.
3. When modifying an existing app, preserve its local Gradle, Android, backend, and UI conventions unless they conflict with the Rokid-specific constraints here.
4. Validate with the app's native commands. For Python backends, use `uv run -- ...`; assume macOS or a nearby Unix environment, not Windows.

## Non-Negotiables

- Rokid tap/select is `KeyEvent.KEYCODE_ENTER`. Do not implement temple tap using `KeyEvent.KEYCODE_DPAD_CENTER`.
- Rokid HUD UI should be monochrome: black background, white foreground, readable typography, and spacing. Do not rely on color semantics.
- Target the Rokid HUD as 480x640 physical pixels at 240 dpi, portrait 3:4.
- Keep root-screen back/exit behavior available. Avoid trapping users in a HUD.
- Prefer `gpt-realtime-1.5` for OpenAI Realtime integrations.
- Keep API keys on a backend. Android should call your own session broker, not OpenAI/Overshoot with secrets embedded.
- Local HTTP backends need Android cleartext traffic enabled or an HTTPS tunnel.

## References

- Read `references/rokid-device-setup.md` for device connection, ADB, Android Studio, and emulator setup.
- Read `references/rokid-android-patterns.md` for HUD layout, touchpad keys, CameraX, Vosk voice commands, and speaker feedback.
- Read `references/rokid-media-webrtc.md` for Android WebRTC video/audio sessions, SDP signaling, data channels, and ICE/TURN details.
- Read `references/openai-realtime.md` for OpenAI Realtime WebRTC brokering, sideband events, transcripts, and backend-controlled speech.
- Read `references/overshoot.md` for Overshoot live-video streams, prompt switching, result relay, and stream lifecycle.
- Read `references/rfdetr.md` for FastAPI/aiortc RF-DETR object detection and detection-driven HUD updates.
- Read `references/server-authoritative-workflows.md` for backend-owned workflow state, prompt switching, HUD state, and exact speech orchestration.

## Starter Asset

`assets/rokid-hello-world/` is a standalone minimal Kotlin Android project. It includes the Gradle wrapper, a single `MainActivity`, and `RokidHudViewportLayout`.

Build it after copying:

```bash
cd rokid-hello-world
./gradlew :app:assembleDebug
```
