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
      <th width="33%">Drink-making coach</th>
      <th width="33%">Sushi speedrun HUD</th>
      <th width="33%">IKEA assembly assistant</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/f11631f9-6ce2-4524-9634-4b4746f64fab" width="260" controls></video>
      </td>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/0dcaf9aa-35c7-49a4-971d-8ef7645715da" width="260" controls></video>
      </td>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/370fe9d7-09ea-45a7-bd09-5ab090e550bc" width="260" controls></video>
      </td>
    </tr>
    <tr>
      <td width="33%" valign="top">
        <a href="examples/rokid-overshoot-openai-realtime">Code ➡️</a>
        <br><br>
        Proactive drink-making assistant for Rokid Glasses. Streams live camera video to Overshoot for scene understanding and uses the OpenAI Realtime API for low-latency spoken guidance and transcript streaming.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-rfdetr">Code ➡️</a>
        <br><br>
        Real-world speedrun HUD for Rokid Glasses. Streams video over WebRTC with a data channel to the backend, which runs a fine-tuned RF-DETR object detector for automatic, hands-free split completion based on a configured route.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-openai-realtime">Code ➡️</a> ·
        <a href="examples/rokid-openai-realtime-rfdetr">Code (+ RF-DETR) ➡️</a>
        <br><br>
        Vision-enabled voice assistant for Rokid Glasses. Streams mic + camera to the OpenAI Realtime API over WebRTC for spoken IKEA assembly guidance. The RF-DETR variant adds object detection for stronger visual understanding.
      </td>
    </tr>
    <tr>
      <th width="33%">Life Context for AI</th>
      <th width="33%">Privacy filter</th>
      <th width="33%">Scene-description HUD</th>
    </tr>
    <tr>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/f285bff2-ebde-4d17-99e0-bd1573881d26" width="260" controls></video>
      </td>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/42f0eee9-6366-4078-abc0-0226a8b8b1aa" width="260" controls></video>
      </td>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/3f412e40-009d-402a-9c3b-a2a28d0a010b" width="260" controls></video>
      </td>
    </tr>
    <tr>
      <td width="33%" valign="top">
        Smart glasses capture an entire day and let you browse and query the footage with AI.
        <br><br>
        <a href="https://dev.to/tash-2s/i-recorded-13-hours-of-my-day-with-smart-glasses-for-ai-heres-what-i-built-and-what-i-learned-5f1c">Read the build write-up</a>
      </td>
      <td width="33%" valign="top">
        <a href="archive/privacy-filter">Code ➡️</a>
        <br><br>
        Real-time privacy filter that sits between the camera and app. Anonymizes faces without consent, detects and remembers verbal consent, and runs locally with recording support.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-overshoot">Code ➡️</a>
        <br><br>
        Simple Rokid Glasses app that streams camera video to Overshoot and shows live inference text on the HUD.
      </td>
    </tr>
    <tr>
      <th width="33%">Voice command + phone support</th>
      <th width="33%"></th>
      <th width="33%"></th>
    </tr>
    <tr>
      <td width="33%" valign="top" align="center">
        <video src="https://github.com/user-attachments/assets/f97bb15e-ada5-4029-ac5a-343e9dfbdd92" width="260" controls></video>
      </td>
      <td width="33%" valign="top" align="center"></td>
      <td width="33%" valign="top" align="center"></td>
    </tr>
    <tr>
      <td width="33%" valign="top">
        <a href="examples/rokid-feature-demo">Code ➡️</a>
        <br><br>
        Reference app for Rokid Glasses voice commands and Android phone/emulator support. Includes camera, microphone, speaker, and menu-screen patterns with touchscreen controls that mirror the Rokid touchpad.
      </td>
      <td width="33%" valign="top"></td>
      <td width="33%" valign="top"></td>
    </tr>
  </tbody>
</table>

## How to use

There are two common ways to start with GlassKit: install the agent skill for guided development, or copy an example and build from it.

### 1. Install the agent skill

Use this when you want Codex, Claude Code, Cursor, or another coding agent to apply the GlassKit patterns while it works on your app.

Install it with [the skills CLI](https://github.com/vercel-labs/skills):

```sh
npx skills add RealComputer/GlassKit
```

Update the skill later with:

```sh
npx skills update glasskit
```

Then ask your coding agent with prompts like:

- "Create a starter Rokid Glasses app using the GlassKit skill."
- "Add a camera preview to the first screen of this Rokid Glasses app."
- "Add Rokid touchpad navigation and a menu screen to this app."
- "Stream the Rokid camera and microphone to a WebRTC backend."

### 2. Copy an example

Use this when one of the examples already matches the app you want to build. Pick the closest example from the table above, copy it into your own project, then follow that example's README.

For example, to copy `examples/rokid-feature-demo` into a new `rokid/` directory:

```sh
git clone https://github.com/RealComputer/GlassKit.git
mkdir rokid
git -C GlassKit archive HEAD:examples/rokid-feature-demo | tar -x -C rokid
```

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
