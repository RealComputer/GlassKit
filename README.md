# GlassKit

**GlassKit is an open-source toolkit for building smart-glasses AI apps.** Your AI coding agent can use the skill, docs, and runnable examples to build apps that understand what wearers see and hear, then guide them in real time.

GlassKit currently focuses on Rokid Glasses. The long-term goal is a developer platform for building, hosting, and shipping smart-glasses apps across more devices, making it easier for anyone to create useful AI apps for glasses.

GlassKit is used by developers building glasses apps for real-world tasks, from manufacturing workflows to field support.

<p align="center">
  https://glasskit.ai/docs
  &nbsp;&middot;&nbsp;
  https://x.com/GlassKit_ai
  &nbsp;&middot;&nbsp;
  https://discord.gg/v5ayGKhPNP
</p>

## Demos

These demos cover the core GlassKit building blocks for Rokid Glasses: camera/mic capture, WebRTC streaming, a monochrome on-lens display (HUD), touchpad and offline voice controls, OpenAI Realtime, Overshoot, and object detection.

<table>
  <thead>
    <tr>
      <th>Drink-making coach</th>
      <th>Sushi speedrun timer</th>
      <th>IKEA assembly assistant</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td align="center">
        <video controls src="https://github.com/user-attachments/assets/f11631f9-6ce2-4524-9634-4b4746f64fab"></video>
      </td>
      <td align="center">
        <video controls src="https://github.com/user-attachments/assets/0dcaf9aa-35c7-49a4-971d-8ef7645715da"></video>
      </td>
      <td align="center">
        <video controls src="https://github.com/user-attachments/assets/370fe9d7-09ea-45a7-bd09-5ab090e550bc"></video>
      </td>
    </tr>
    <tr>
      <td width="33%" valign="top">
        <a href="examples/rokid-overshoot-openai-realtime">Code</a>
        <br>
        Proactive drink-making coach that watches ingredients, picks a recipe, and guides each step. Combines Overshoot video inference, recipe state, OpenAI Realtime, and HUD guidance.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-rfdetr">Code</a>
        <br>
        Real-world speedrun timer for physical tasks, shown with sushi. Uses RF-DETR to detect configured objects and advance HUD splits after confirmation.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-openai-realtime">Code</a> /
        <a href="examples/rokid-openai-realtime-rfdetr">Code with RF-DETR</a>
        <br>
        Voice-first assembly assistant for an IKEA wooden box. Streams mic/camera input to OpenAI Realtime, with an RF-DETR variant for object-aware guidance.
      </td>
    </tr>
    <tr>
      <th>Searchable life recording</th>
      <th>Real-time privacy filter</th>
      <th>Live scene reader</th>
    </tr>
    <tr>
      <td align="center">
        <video controls src="https://github.com/user-attachments/assets/f285bff2-ebde-4d17-99e0-bd1573881d26"></video>
      </td>
      <td align="center">
        <video controls src="https://github.com/user-attachments/assets/42f0eee9-6366-4078-abc0-0226a8b8b1aa"></video>
      </td>
      <td align="center">
        <video controls src="https://github.com/user-attachments/assets/3f412e40-009d-402a-9c3b-a2a28d0a010b"></video>
      </td>
    </tr>
    <tr>
      <td width="33%" valign="top">
        Full-day smart-glasses recording demo. Makes long first-person recordings browsable and searchable.
        <br>
        <a href="https://dev.to/tash-2s/i-recorded-13-hours-of-my-day-with-smart-glasses-for-ai-heres-what-i-built-and-what-i-learned-5f1c">Read the build write-up</a>
      </td>
      <td width="33%" valign="top">
        <a href="archive/privacy-filter">Code</a>
        <br>
        Real-time privacy layer between a camera and an app. Anonymizes video locally and tracks spoken consent.
      </td>
      <td width="33%" valign="top">
        <a href="examples/rokid-overshoot">Code</a>
        <br>
        Simple real-time scene reader that keeps describing what the wearer is looking at. Sends live camera context to Overshoot and displays inference text on the HUD.
      </td>
    </tr>
    <tr>
      <th>Rokid feature demo</th>
      <th></th>
      <th></th>
    </tr>
    <tr>
      <td align="center">
        <video controls src="https://github.com/user-attachments/assets/f97bb15e-ada5-4029-ac5a-343e9dfbdd92"></video>
      </td>
      <td align="center"></td>
      <td align="center"></td>
    </tr>
    <tr>
      <td width="33%" valign="top">
        <a href="examples/rokid-feature-demo">Code</a>
        <br>
        Device-feature reference app for Rokid Glasses and phone/emulator testing. Covers touchpad navigation, offline Vosk voice commands, camera, mic, audio, and reusable screen controllers.
      </td>
      <td></td>
      <td></td>
    </tr>
  </tbody>
</table>

## Quick Start

There are three ways to start, depending on how you like to build.

### 1. Install the GlassKit agent skill

Use this when you want Codex, Claude Code, Cursor, or another coding agent to understand smart-glasses app development while it builds your app.

Smart-glasses apps have unique aspects that coding agents are not used to handling: vision AI pipelines, small HUDs, camera, microphone, and sensor access, touchpad and voice inputs, battery use, and wearer-facing UX. The GlassKit agent skill packages that context with reference patterns and a starter template, so agents can build more realistic glasses apps from the first pass.

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

## Repository Map

| Path | What it contains |
| --- | --- |
| [`skills/glasskit/`](skills/glasskit/SKILL.md) | Agent skill, Rokid Glasses starter, and smart-glasses app references for coding agents and human developers. |
| [`cli/`](cli/README.md) | `glasskit` command-line tools, including recorded-video evals for apps. |
| [`docs/`](docs) | Hardware setup, Rokid Glasses device notes, and demo-recording workflow. |
| [`examples/`](examples) | Runnable Rokid Glasses examples you can copy or adapt. |

## How Apps Work

A typical app in this repo has four pieces:

1. A Rokid Glasses app (Android) captures camera/microphone input, handles touchpad gestures, and renders a HUD.
2. WebRTC carries live media between the glasses, your backend, and AI services.
3. A backend coordinates session setup, workflow state, model calls, tool calls, and app-specific decisions.
4. The wearer gets real-time feedback via display and audio.

The exact architecture varies by example. Some pieces can run offline, including local voice commands, device controls, and local vision/privacy processing.

## Requirements

Many examples need:

- [Rokid Glasses and a development cable](docs/how-to-get-rokid-glasses.md)
- Android Studio or `adb`
- `uv` for Python backends or `node` for TypeScript backends
- API keys depending on the example, such as `OPENAI_API_KEY`, `OVERSHOOT_API_KEY`, or `ROBOFLOW_API_KEY`

Each example README has the exact setup steps and environment variables.

## Contributing

Contributions are welcome.

By submitting a pull request, you agree that your contribution is licensed under the MIT License of this project (see LICENSE), and you confirm that you have the right to submit it under those terms.
