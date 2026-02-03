# GlassKit

Build *smart* AI assistants for *smart glasses*, fast.

GlassKit is an open-source dev suite for building reliable, vision-enabled smart glasses apps. The long-term goal is an SDK + cloud platform that turns real-time camera and mic streams into specialized AI responses, tailored to your workflow. **Today, this repo is a set of end-to-end examples you can fork and adapt** (plus a privacy filter project).

- Updates: https://x.com/GlassKit_ai
- Discord: https://discord.gg/v5ayGKhPNP
- Email: tash@glasskit.ai

## Demos (watch first)

| IKEA assembly assistant (Realtime voice + vision) | Sushi speedrun HUD (Object detection) | Real-time privacy filter (Offline) |
| --- | --- | --- |
| https://github.com/user-attachments/assets/370fe9d7-09ea-45a7-bd09-5ab090e550bc | https://github.com/user-attachments/assets/0dcaf9aa-35c7-49a4-971d-8ef7645715da | https://github.com/user-attachments/assets/42f0eee9-6366-4078-abc0-0226a8b8b1aa |

If the videos don't render in the table above, GitHub usually renders them when they're on their own line:

https://github.com/user-attachments/assets/370fe9d7-09ea-45a7-bd09-5ab090e550bc

https://github.com/user-attachments/assets/0dcaf9aa-35c7-49a4-971d-8ef7645715da

https://github.com/user-attachments/assets/42f0eee9-6366-4078-abc0-0226a8b8b1aa

## Why GlassKit

Smart glasses apps are hard. Generic vision-capable LLMs often fail at real-world task support, and each glasses brand has different hardware, form factors, and frameworks.

GlassKit is built around the idea that *reliability comes from orchestration*:

- Vision model orchestration (use the right model(s) for the job, not just "one prompt").
- Visual context management (what the assistant should remember/ignore, and how it's represented).
- Real-time streaming (camera + mic in, responses out) with sane developer ergonomics.
- Templates and end-to-end reference apps you can actually ship from.

## How It Works (the vision)

You define your assistant with visual/textual context and your business logic. Then your app works like this:

1. Camera frames and audio stream from the glasses to the cloud via the SDK
2. The cloud processes inputs using vision models and LLMs with your custom context + logic
3. Responses stream back to the glasses and the wearer via the SDK

You handle the app logic. GlassKit handles the glasses-to-AI pipeline.

## What's In This Repo (start here)

Each project below is fully end-to-end and has its own setup guide. Pick the closest one to your use case and fork it.

- [Rokid Glasses x OpenAI Realtime API](examples/rokid-openai-realtime/README.md): Real-time voice assistant (audio + camera over WebRTC) with a Node backend for session brokering + tool calls. (IKEA assembly reference scenario.)
- [Rokid Glasses x OpenAI Realtime API x RF-DETR](examples/rokid-openai-realtime-rfdetr/README.md): Same assistant, but adds backend RF-DETR object detection + annotated-frame injection for more specialized visual understanding. (Same IKEA demo video.)
- [Rokid Glasses x Object Detection (RF-DETR)](examples/rokid-rfdetr/README.md): Vision-only speedrun HUD driven by detections (timers, split logic, and two-hit confirmation). (Sushi speedrun included.)
- [Privacy Filter](archive/privacy-filter/README.md): Offline, real-time privacy infrastructure (face anonymization + consent detection) that can sit between a camera feed and downstream apps.

## Status

GlassKit is early, but useful now:

- The examples show working glasses-to-AI pipelines (Android on-device code + a backend you control).
- The SDK + cloud platform are the direction this repo is heading next.
- Platform support is currently focused on Rokid Glasses; broader platform support is planned (Meta glasses, Android XR, Mentra, and more).

## License

MIT (see [LICENSE](LICENSE)).

## Repo Description Ideas

Current: "An open-source dev suite for building reliable, vision-enabled smart glasses apps."

Alternatives (pick one):

- "Open-source SDK + reference apps for building reliable AI assistants on smart glasses."
- "Build real-time, vision-enabled smart glasses apps: SDK (soon) + end-to-end examples (now)."
- "The open-source glasses-to-AI pipeline: streaming, vision orchestration, and reference apps."
