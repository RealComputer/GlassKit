---
name: glasskit
description: Use when starting, modifying, or debugging a Rokid Glasses smart glasses app. This includes templates and common implementation patterns for HUD UI, camera/mic/speaker access, temple touchpad handling, WebRTC streaming, voice controls, real-time LLM/VLM integration, CV object detection, and best practices.
---

# GlassKit

This GlassKit skill provides templates and documentation for Rokid Glasses app development.

## Rokid Glasses Basics

- Rokid Glasses are Android-based smart glasses with an outward-facing camera, a monochrome HUD, microphones, speakers, and a temple touchpad. They do not have a touchscreen.
- Rokid makes several glasses products; this skill specifically targets the product named "Rokid Glasses".
- Rokid Glasses have a green monochrome binocular display with a portrait 480x640 HUD. Use black backgrounds and white foregrounds; on the device, black appears transparent and white appears green. Other colors can be used for media such as images, but the device renders them as green, transparent, or intermediate brightness levels.
- The temple touchpad supports four common controls: tap for select, double-tap for back, swipe forward for next, and swipe backward for previous. Keep double-tap available on the root screen so users can exit the app.
- You can build Rokid Glasses apps like Android phone apps, but the glasses have less CPU and RAM than phones, so implementations should be efficient. Camera and microphone behavior also has device-specific constraints; consult the relevant references below.

## Workflow

1. For a new Rokid Glasses app, copy `assets/rokid-hello-world/` into the target workspace first. It is a small starter app. Rename the package and application ID after copying if needed.
2. Identify the required features, then read the relevant references below before implementation so you can account for device-specific constraints and patterns.
3. For questions, open an issue in the upstream [GlassKit repository](https://github.com/RealComputer/GlassKit) or ask in [the Discord server](https://discord.gg/v5ayGKhPNP).

## References

- Read `references/rokid-device-setup.md` for device connection, ADB, Android Studio, and emulator setup.
- Read `references/rokid-android-patterns.md` for HUD layout, touchpad keys, CameraX, Vosk voice commands, and speaker feedback.
- Read `references/rokid-media-webrtc.md` for Android WebRTC video/audio sessions, SDP signaling, data channels, and ICE/TURN details.
- Read `references/openai-realtime.md` for OpenAI Realtime WebRTC brokering, sideband events, transcripts, and backend-controlled speech.
- Read `references/overshoot.md` for Overshoot live-video streams, prompt switching, result relay, and stream lifecycle.
- Read `references/rfdetr.md` for FastAPI/aiortc RF-DETR object detection and detection-driven HUD updates.
- Read `references/server-authoritative-workflows.md` for backend-owned workflow state, prompt switching, HUD state, and exact speech orchestration.
