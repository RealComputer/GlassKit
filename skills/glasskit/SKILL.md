---
name: glasskit
description: Use when you start building a Rokid Glasses (smart glasses) app, or when you modify or debug existing Rokid Glasses apps. This includes templates and commmon implementation patterns, including a getting started template, display UI on HUD, camera/mic/speaker access, temple touchpad handling, WebRTC streaming, voice controls, realtime LLM/VLM integration, CV object detection integration, and best practices.
---

# GlassKit

This GlassKit skill provides useful templates and docs for Rokid Glasses app development.

## Basics

- Rokid Glasses are Android-based smart glasses with an outward camera, a monochrome HUD, microphones, speakers, and a temple touchpad. No touchscreen.
- Rokid Glasses are developed by Rokid. Rokid has several other glasses, and this doc specifically targets their "Rokid Glasses", so do not confuse with their other glasses product.
- Rokid Glasses have an green monochrome binocular display on the lenses. Use black for background and white for foreground, and they're shown in transparent and green accordingly. You can still use any other colors (e.g., displaying pictures), but they're always shown in green, transparent, and everything in between on the actual device.
- You can build Rokid Glasses apps like Android phone apps, but Rokid Glasses have less computation power (CPU and RAM) than phones, so the implementation is preffered to be efficient. Also, camera and mic have some restrictions, so please refer the references below.
- Target the Rokid HUD as 480x640 physical pixels (portrait 3:4) at 240 dpi.
- Keep root-screen back/exit behavior available. Avoid trapping users in a HUD.

## Workflow

1. For a new Rokid Glasses app, copy `assets/rokid-hello-world/` into the target workspace first. Rename the package/application id after copying if necessary.
2. Identify the necessary features and read the relevant references below for implementation to understand device specific constraints and patterns.
3. For any questions, you can open an issue on the upstream [GlassKit repository](https://github.com/RealComputer/GlassKit), or ask questions in [the Discord server](https://discord.gg/v5ayGKhPNP).

## References

- Read `references/rokid-device-setup.md` for device connection, ADB, Android Studio, and emulator setup.
- Read `references/rokid-android-patterns.md` for HUD layout, touchpad keys, CameraX, Vosk voice commands, and speaker feedback.
- Read `references/rokid-media-webrtc.md` for Android WebRTC video/audio sessions, SDP signaling, data channels, and ICE/TURN details.
- Read `references/openai-realtime.md` for OpenAI Realtime WebRTC brokering, sideband events, transcripts, and backend-controlled speech.
- Read `references/overshoot.md` for Overshoot live-video streams, prompt switching, result relay, and stream lifecycle.
- Read `references/rfdetr.md` for FastAPI/aiortc RF-DETR object detection and detection-driven HUD updates.
- Read `references/server-authoritative-workflows.md` for backend-owned workflow state, prompt switching, HUD state, and exact speech orchestration.

## Starter Asset

`assets/rokid-hello-world/` is a minimal Kotlin Android project. It includes the Gradle wrapper, a single `MainActivity`, and `RokidHudViewportLayout`.

Build it after copying:

```bash
cd rokid-hello-world
./gradlew :app:assembleDebug
```

## Tips

- `./gradlew build` for checking Android builds
- Use `adb` for connected devices and `emulator` for Android Emulator
