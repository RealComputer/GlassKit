# GlassKit

Build *smart* AI apps for *smart glasses*, fast.

**GlassKit is an open-source dev suite for building vision-enabled smart glasses apps.** It provides SDKs and backends that turn real-time camera and microphone streams into specialized AI responses and actions, tailored to your workflow.

**Today:** this repository focuses on end-to-end examples you can adapt.
**Next:** reusable SDKs + a production-ready backend are coming up.

<div align="center">

https://glasskit.ai • https://x.com/GlassKit_ai • https://discord.gg/v5ayGKhPNP

</div>

## Examples/Templates you can use

<table width="100%">
  <thead>
    <tr>
      <th width="33%">IKEA assembly assistant</th>
      <th width="33%">Sushi speedrun HUD</th>
      <th width="33%">Privacy filter</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/370fe9d7-09ea-45a7-bd09-5ab090e550bc" width="260" controls></video>
      </td>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/0dcaf9aa-35c7-49a4-971d-8ef7645715da" width="260" controls></video>
      </td>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/42f0eee9-6366-4078-abc0-0226a8b8b1aa" width="260" controls></video>
      </td>
    </tr>
    <tr>
      <td width="33%" valign="top">
        <a href="examples/rokid-openai-realtime">Code ➡️</a> ·
        <a href="examples/rokid-openai-realtime-rfdetr">Code (+ RF-DETR) ➡️</a>
        <br><br>
        Real-time, vision-enabled voice assistant for Rokid Glasses. Streams mic + camera over WebRTC to the OpenAI Realtime API, plays back speech, and uses tool calls to guide tasks like IKEA assembly steps.
        <br><br>
        The RF-DETR variant adds object detection and passes annotated frames to OpenAI for better visual understanding.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-rfdetr">Code ➡️</a>
        <br><br>
        Real-world speedrun HUD for Rokid Glasses. Streams video over WebRTC with a data channel to the backend, which runs a fine-tuned RF-DETR object detector for automatic, hands-free split completion based on a configured route.
      </td>
      <td width="33%" valign="top">
        <a href="archive/privacy-filter">Code ➡️</a>
        <br><br>
        Real-time privacy filter that sits between the camera and app. Anonymizes faces without consent, detects and remembers verbal consent, and runs locally with recording support.
      </td>
    </tr>
  </tbody>
</table>

## Why GlassKit

Smart glasses apps are hard.

- Generic vision-capable LLMs often fail at real-world task support.
- Each glasses brand has different hardware, form factors, and frameworks.
- Real-time camera + mic streaming is non-trivial to build correctly and ergonomically.

GlassKit is built around:

- **Vision model orchestration:** choose the right mix of multimodal LLMs and object detectors for the job.
- **Visual context management:** define what the AI should know and how it is represented.
- **Real-time streaming:** camera + mic in, responses out, with sane developer ergonomics.

## How it works

You define your AI with visual/textual context and your business logic. Then your app works like this:

1. Camera frames and audio stream from the glasses to the backend via the SDK
2. The backend processes inputs using vision models and LLMs with your custom context + logic
3. Responses stream back to the glasses and the wearer via the SDK

You handle the app logic. GlassKit handles the glasses-to-AI pipeline.

## Getting started

1. **Pick an example** from `examples/`
2. **Open its README** and follow the setup steps
3. **Run it**, then modify for your workflow

## Status and roadmap

GlassKit is early and under active development, but the examples are usable today.

- **Current focus:** end-to-end templates you can clone and adapt
- **Coming next:** reusable SDKs + production-ready backends
- **Developer experience:** demo video recording tooling; observability + debuggability tools
- **Platform support today:** Rokid Glasses
- **Planned support:** Meta glasses, Android XR, Mentra, and more

## Contributing

**Contributions are welcome!**

By submitting a pull request, you agree that your contribution is licensed under the MIT License of this project (see LICENSE), and you confirm that you have the right to submit it under those terms.
