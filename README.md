# GlassKit

Build *smart* AI apps for *smart glasses*, fast.

GlassKit is an open-source dev suite for building vision-enabled smart glasses apps. This provides SDKs and backends that turns real-time camera and mic streams into specialized AI responses and actions, tailored to your workflow. Today, this repository mainly consists of end-to-end examples you can adapt.

<div align="center">
https://glasskit.ai • https://x.com/GlassKit_ai • https://discord.gg/v5ayGKhPNP
</div>

## Example Projects

| IKEA assembly assistant | Sushi speedrun HUD | Privacy filter |
| --- | --- | --- |
| <video src="https://github.com/user-attachments/assets/370fe9d7-09ea-45a7-bd09-5ab090e550bc"></video> | <video src="https://github.com/user-attachments/assets/0dcaf9aa-35c7-49a4-971d-8ef7645715da"></video> | <video src="https://github.com/user-attachments/assets/42f0eee9-6366-4078-abc0-0226a8b8b1aa"></video> |
| Start here (two variants):<br>[Rokid x OpenAI Realtime API](examples/rokid-openai-realtime/README.md)<br>[Realtime + RF-DETR](examples/rokid-openai-realtime-rfdetr/README.md)<br><br>Realtime voice assistant that sees progress, answers questions, and guides step-by-step. | Start here:<br>[Rokid x Object Detection (RF-DETR)](examples/rokid-rfdetr/README.md)<br><br>Vision-only speedrun template: HUD, timers, and hands-free split detection. | Start here:<br>[Privacy Filter](archive/privacy-filter/README.md)<br><br>Offline, real-time face anonymization + consent detection for camera-based apps. |

## Why GlassKit

Smart glasses apps are hard. Generic vision-capable LLMs often fail at real-world task support, and each glasses brand has different hardware, form factors, and frameworks.

GlassKit is built around the idea that *reliability comes from orchestration*:

- Vision model orchestration (use the right model(s) for the job, not just "one prompt").
- Visual context management (what the assistant should know, and how it's represented).
- Real-time streaming (camera + mic in, responses out) with sane developer ergonomics.
- Templates and end-to-end reference apps you can actually ship from.

## How It Works

You define your assistant with visual/textual context and your business logic. Then your app works like this:

1. Camera frames and audio stream from the glasses to the backend via the SDK
2. The backend processes inputs using vision models and LLMs with your custom context + logic
3. Responses stream back to the glasses and the wearer via the SDK

You handle the app logic. GlassKit handles the glasses-to-AI pipeline.

## Status

GlassKit is early, but useful now.

- The SDKs + established backends are coming.
- Platform support is currently focused on Rokid Glasses; broader platform support is planned (Meta glasses, Android XR, Mentra, and more).
