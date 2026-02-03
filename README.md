# GlassKit

Build *smart* AI apps for *smart glasses*, fast.

GlassKit is an open-source dev suite for building vision-enabled smart glasses apps. It provides SDKs and backends that turn real-time camera and microphone streams into specialized AI responses and actions, tailored to your workflow. **For now, this repository focuses on end-to-end examples you can adapt.**

<div align="center">
https://glasskit.ai • https://x.com/GlassKit_ai • https://discord.gg/v5ayGKhPNP
</div>

## Example Projects

| IKEA assembly assistant | Sushi speedrun HUD | Privacy filter |
| --- | --- | --- |
| <video src="https://github.com/user-attachments/assets/370fe9d7-09ea-45a7-bd09-5ab090e550bc"></video> | <video src="https://github.com/user-attachments/assets/0dcaf9aa-35c7-49a4-971d-8ef7645715da"></video> | <video src="https://github.com/user-attachments/assets/42f0eee9-6366-4078-abc0-0226a8b8b1aa"></video> |
| [Code ➡️](examples/rokid-openai-realtime) · [Code (+ RF-DETR) ➡️](examples/rokid-openai-realtime-rfdetr)<br><br>Real-time, vision-enabled voice assistant for Rokid Glasses. Streams mic + camera over WebRTC to the OpenAI Realtime API, plays back speech, and uses tool calls to guide tasks like IKEA assembly steps. The RF-DETR variant adds object detection and passes annotated frames to OpenAI for better visual understanding. | [Code ➡️](examples/rokid-rfdetr)<br><br>Real-world speedrun HUD for Rokid Glasses. Uses RF-DETR for automatic, hands-free split completion, based on a configured route. | [Code ➡️](archive/privacy-filter)<br><br>Real-time privacy filter that sits between the camera and app. Anonymizes faces without consent, detects and remembers verbal consent, and runs locally with recording support. |

## Why GlassKit

Smart glasses apps are hard. Generic vision-capable LLMs often fail at real-world task support, and each glasses brand has different hardware, form factors, and frameworks.

GlassKit is built around:

- Vision model orchestration: choose the right mix of multimodal LLMs and object detectors for the job.
- Visual context management: define what the AI should know and how it's represented.
- Real-time streaming: camera + mic in, responses out, with sane developer ergonomics.

## The Idea

You define your AI with visual/textual context and your business logic. Then your app works like this:

1. Camera frames and audio stream from the glasses to the backend via the SDK
2. The backend processes inputs using vision models and LLMs with your custom context + logic
3. Responses stream back to the glasses and the wearer via the SDK

You handle the app logic. GlassKit handles the glasses-to-AI pipeline.

## Status

GlassKit is early and under active development, but the examples are usable today.

- The SDKs and production-ready backends are coming. Stay tuned!
- Platform support is currently focused on Rokid Glasses; broader platform support is planned (Meta glasses, Android XR, Mentra, and more).
