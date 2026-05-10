# GlassKit

**GlassKit is an open-source toolkit for building smart-glasses AI apps.** Your AI coding agent can use the included skill, docs, and runnable examples to build apps that understand what wearers see and hear, then guide them in real time.

GlassKit starts with Rokid Glasses and is growing into a developer platform for building, hosting, and shipping smart-glasses apps across more devices, making it easier for anyone to create useful AI apps for glasses.

<div align="center">

https://glasskit.ai - https://x.com/GlassKit_ai - https://discord.gg/v5ayGKhPNP

</div>

## Demos

These demos show the main pieces GlassKit supports today for Rokid Glasses: camera and microphone capture, monochrome HUD rendering, touchpad and offline voice controls, WebRTC media streaming, and integrations with OpenAI Realtime, Overshoot, and object detection workflows.

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
        <a href="examples/rokid-overshoot-openai-realtime">Code</a>
        <br><br>
        Proactive mocktail coach for Rokid Glasses. The backend watches live Overshoot observations, chooses a recipe, advances steps, and uses OpenAI Realtime for short spoken guidance and HUD transcripts.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-rfdetr">Code</a>
        <br><br>
        Real-world speedrun timer for Rokid Glasses. The glasses stream video to a FastAPI backend, RF-DETR recognizes configured objects, and the HUD advances splits hands-free after confirmation.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-openai-realtime">Code</a> /
        <a href="examples/rokid-openai-realtime-rfdetr">Code with RF-DETR</a>
        <br><br>
        Voice-first assembly assistant for Rokid Glasses. The base version streams mic and camera data to OpenAI Realtime over WebRTC; the RF-DETR variant adds backend object detection and annotated-frame injection for stronger part awareness.
      </td>
    </tr>
    <tr>
      <th width="33%">Life context for AI</th>
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
        Demo write-up about recording a full day from smart glasses and making the footage searchable with AI.
        <br><br>
        <a href="https://dev.to/tash-2s/i-recorded-13-hours-of-my-day-with-smart-glasses-for-ai-heres-what-i-built-and-what-i-learned-5f1c">Read the build write-up</a>
      </td>
      <td width="33%" valign="top">
        <a href="archive/privacy-filter">Code</a>
        <br><br>
        Prototype privacy layer that sits between a camera and an app. It can anonymize faces, track verbal consent, and run locally with recording support.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-overshoot">Code</a>
        <br><br>
        Smallest live-video example. Rokid Glasses stream camera video to Overshoot and render returned scene text on the HUD.
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
        <a href="examples/rokid-feature-demo">Code</a>
        <br><br>
        Device-feature reference app for touchpad navigation, offline Vosk commands, camera preview, mic levels, speaker output, menu screens, and Android phone/emulator controls.
      </td>
      <td width="33%" valign="top"></td>
      <td width="33%" valign="top"></td>
    </tr>
  </tbody>
</table>

## Quick Start

There are three ways to start, depending on how you like to build.

### 1. Install the GlassKit agent skill

Use this when you want Codex, Claude Code, Cursor, or another coding agent to understand smart-glasses app development while it builds your app. Smart-glasses apps have device specs, sensor access, display constraints, input patterns, and wearer-facing UX details that general coding agents often miss. The GlassKit agent skill gives the agent that context, plus a Rokid starter template for new apps.

Install it with [the Agent Skills CLI](https://github.com/vercel-labs/skills):

```sh
npx skills add RealComputer/GlassKit
```

Update it later with:

```sh
npx skills update glasskit
```

Then ask your coding agent with prompts like: `create a starter rokid glasses app`, `add a camera preview to the first screen using the glasskit skill`, or `create a rokid glasses app that connects to openai realtime and talks about what it sees`.

### 2. Copy the Rokid starter app

Use this when you want a small app scaffold with Rokid HUD layout and navigation patterns. You can copy it manually or run:

```sh
git clone https://github.com/RealComputer/GlassKit.git
mkdir rokid-starter
git -C GlassKit archive HEAD:skills/glasskit/assets/rokid-hello-world | tar -x -C rokid-starter
```

Then follow [the README](skills/glasskit/assets/rokid-hello-world/README.md).

### 3. Copy a complete example

Use this when a demo is close to the app you want to build. For example, to copy `examples/rokid-feature-demo`:

```sh
git clone https://github.com/RealComputer/GlassKit.git
mkdir my-glasses-app
git -C GlassKit archive HEAD:examples/rokid-feature-demo | tar -x -C my-glasses-app
```

Then follow that example's README.

## How GlassKit Apps Work

A typical app in this repo has four pieces:

1. A Rokid Android app captures camera and/or microphone input, handles touchpad gestures, and renders a small HUD.
2. WebRTC carries live media between the glasses, your backend, and AI services.
3. A backend coordinates session setup, workflow state, model calls, tool calls, and app-specific decisions.
4. The wearer gets guidance through HUD updates, speech, transcripts, timers, or other state events.

The exact architecture depends on the example. Some apps send media directly to OpenAI Realtime. Some terminate video on a Python backend with `aiortc`. Some use Overshoot for live video understanding or RF-DETR for object detection.

## Repository Map

| Path | What it is for |
| --- | --- |
| [`skills/glasskit`](skills/glasskit/SKILL.md) | Agent skill, Rokid Glasses starter app, and focused references. Useful for both coding agents and human developers. |
| [`docs`](docs) | Hardware setup, Rokid Glasses device notes, and demo-recording workflow. |
| [`examples`](examples) | Runnable Rokid Glasses examples. |

## Requirements

Most examples need:

- [Rokid Glasses and a development cable](docs/how-to-get-rokid-glasses.md)
- Android Studio and `adb`
- `uv` for Python backends or Node.js for TypeScript backends
- API keys depending on the example, such as `OPENAI_API_KEY`, `OVERSHOOT_API_KEY`, or `ROBOFLOW_API_KEY`

Each example README has the exact setup steps and environment variables.

## Contributing

Contributions are welcome.

By submitting a pull request, you agree that your contribution is licensed under the MIT License of this project (see LICENSE), and you confirm that you have the right to submit it under those terms.
