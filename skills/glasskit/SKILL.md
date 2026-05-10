---
name: glasskit
description: Use when starting, modifying, or debugging apps for Rokid Glasses or similar camera glasses. Covers Rokid setup, on-device display and input patterns, camera/mic/speaker access, touchpad controls, WebRTC streaming, voice controls, real-time LLM/VLM integration, proactive workflow apps, CV object detection, and device-specific best practices.
---

# GlassKit

This GlassKit skill provides templates and documentation for Rokid Glasses app development.

## Rokid Glasses Basics

- Rokid Glasses are Android-based smart glasses with an outward-facing camera, a monochrome HUD, microphones, speakers, and a temple touchpad. They do not have a touchscreen.
- Rokid makes several glasses products; this skill specifically targets the product named "Rokid Glasses".
- Rokid Glasses have a green monochrome binocular display with a portrait 480x640 HUD. Use black backgrounds and white foregrounds; on the device, black appears transparent and white appears green. Other colors can be used for media such as images, but the device renders them as green, transparent, or intermediate brightness levels.
- The temple touchpad supports four controls: tap for select, double-tap for back, swipe forward for next, and swipe backward for previous. Keep double-tap available on the root screen so users can exit the app.
- Rokid Glasses do not have cellular networking. Networked apps need device Wi-Fi or internet access through a phone companion app. Most guidance here assumes a standalone glasses app without a phone companion app for simplicity; if building a companion app, also check out Rokid's official [CXR-L SDK](https://ar.rokid.com/sprite?lang=en).
- You can build Rokid Glasses apps like Android phone apps, but the glasses have less CPU and RAM than phones, so implementations should be efficient. Camera and microphone behavior also has device-specific constraints; consult the relevant references below.

## Workflow

1. For a new Rokid Glasses app, copy the [Rokid Hello World starter](assets/rokid-hello-world/) into the target workspace first. It is a small starter app. Rename the package and application ID after copying if needed. You can also compare your app against this starter when troubleshooting setup issues.
2. Identify the required features, then read the relevant references below before implementation so you can account for device-specific constraints and patterns.
3. For questions, open an issue in the upstream [GlassKit repository](https://github.com/RealComputer/GlassKit) or ask in [the Discord server](https://discord.gg/v5ayGKhPNP).

## References

- [Rokid Setup](references/rokid-setup.md): Rokid hardware, Wi-Fi/ADB connection, common commands, and phone/emulator setup.
- [Rokid Inputs](references/rokid-inputs.md): Rokid touchpad handling, camera access, and microphone access.
- [Vosk Voice Commands](references/vosk-voice-commands.md): Vosk setup and implementation pattern for offline command words.
- [Rokid WebRTC](references/rokid-webrtc.md): Rokid WebRTC sessions, including Android video/audio tracks, receive-only audio, SDP signaling, data channels, ICE/TURN, and backend receiver/broker patterns.
- [Proactive Perception Pattern](references/proactive-perception-pattern.md): high-level pattern for proactive glasses apps where continuous observations drive workflow state, wearer feedback, and actions.
- [OpenAI Realtime](references/openai-realtime.md): OpenAI Realtime patterns for smart glasses, including WebRTC media brokering, automatic VAD responses, backend-gated turns for vision/tool/speech workflows, sideband events, and transcripts.
- [Object Detection](references/object-detection.md): model-agnostic object detection patterns for Rokid camera streams, including backend inference, normalized events, detection-driven app events, RF-DETR as an example, and realtime model augmentation.
