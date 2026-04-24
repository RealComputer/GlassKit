# GlassKit Agent Skill Implementation Plan

## Purpose

Create a portable `glasskit` Agent Skill under `skills/glasskit/` that lets an AI coding agent help users build smart-glasses apps with GlassKit patterns without needing access to the rest of this repository. The first supported device family is Rokid Glasses. The skill should package:

- A lean `SKILL.md` that explains when and how to use the skill.
- A minimal standalone Rokid Android hello-world project in `assets/`.
- Focused `references/` guides distilled from the current `examples/` and `docs/`.

Treat this as a distributable agent skill that captures templates, snippets, device-specific constraints, and best-practice patterns.

## Source Material Reviewed

Use these existing repository areas as the source of truth:

- `agent-skills.md`: Agent Skill format, progressive disclosure, frontmatter requirements, and best practices.
- `skills/glasskit/SKILL.md`: current placeholder scaffold.
- `docs/how-to-get-rokid-glasses.md`: device, dev cable, and APK upload guidance.
- `examples/rokid-feature-demo`: Rokid HUD shape, touchpad/input mapping, CameraX preview, microphone/Vosk voice command, speaker test, Android phone/emulator fallback.
- `examples/rokid-openai-realtime`: direct OpenAI Realtime WebRTC audio/video pattern and sideband tool broker. Treat its `gpt-realtime` model value and `KEYCODE_DPAD_CENTER` usage as outdated.
- `examples/rokid-openai-realtime-rfdetr`: OpenAI Realtime plus backend RF-DETR frame injection. Treat its `gpt-realtime` model value and `KEYCODE_DPAD_CENTER` usage as outdated.
- `examples/rokid-overshoot`: minimal Overshoot video streaming and HUD log pattern.
- `examples/rokid-rfdetr`: backend RF-DETR object detection, WebRTC data channel, speedrun HUD, two-hit confirmation, annotated frame capture.
- `examples/rokid-overshoot-openai-realtime`: newest server-authoritative proactive workflow pattern, Overshoot plus OpenAI Realtime, `gpt-realtime-1.5`, exact backend-driven speech, HUD state, recipe schema.

## Agent Skill Constraints

Follow the constraints from `agent-skills.md` and `skill-creator`:

- `skills/glasskit/SKILL.md` must have YAML frontmatter with `name: glasskit` and a trigger-ready `description`.
- Keep `SKILL.md` concise. It should be an overview, workflow, gotchas list, and index. Put detailed guidance in directly linked reference files.
- Use relative links from `SKILL.md` to `references/...` and `assets/...`.
- Keep references one level deep from `SKILL.md`.
- Avoid generic Android/Python explanations. Focus on Rokid Glasses, OpenAI Realtime, Overshoot, RF-DETR, and example-specific contracts that a general model is likely to miss.
- The skill directory must be standalone. Do not point users to `../../examples/...` as required context, because deployed skill users will not have this repository.

## Proposed Skill Layout

```text
skills/glasskit/
├── SKILL.md
├── assets/
│   └── rokid-hello-world/
│       ├── build.gradle.kts
│       ├── settings.gradle.kts
│       ├── gradle.properties
│       ├── gradlew
│       ├── gradlew.bat
│       ├── gradle/
│       │   ├── libs.versions.toml
│       │   └── wrapper/
│       │       ├── gradle-wrapper.jar
│       │       └── gradle-wrapper.properties
│       └── app/
│           ├── build.gradle.kts
│           ├── proguard-rules.pro
│           └── src/main/...
└── references/
    ├── rokid-device-setup.md
    ├── rokid-android-patterns.md
    ├── rokid-media-webrtc.md
    ├── openai-realtime.md
    ├── overshoot.md
    ├── rfdetr.md
    └── server-authoritative-workflows.md
```

## `SKILL.md` Plan

Replace the placeholder with:

- Frontmatter:
  - `name: glasskit`
  - A description under 1024 characters that triggers on building, modifying, or debugging GlassKit smart-glasses apps; Rokid Glasses; monochrome HUDs; touchpad/voice controls; camera/mic/speaker; WebRTC streaming; OpenAI Realtime; Overshoot; RF-DETR/object detection.
- Body:
  - Quick workflow:
    1. If starting a Rokid app from zero, copy `assets/rokid-hello-world/`.
    2. Identify requested feature area.
    3. Read the matching `references/*.md`.
    4. Implement with the local app's existing patterns when modifying an app.
    5. Validate with Gradle/backend commands.
  - Gotchas:
    - Rokid HUD is monochrome; design black/white UI and rely on typography/spacing.
    - The Rokid display target is 480x640 at 240 dpi, 3:4 portrait.
    - Do not block root-screen back/exit behavior.
    - For OpenAI Realtime, prefer `gpt-realtime-1.5` as used by the newest mocktail example.
  - Reference index with explicit "read this when..." guidance.

## Asset Template Plan

Create `assets/rokid-hello-world/` from `examples/rokid-feature-demo`, stripped to the minimum standalone app:

- Keep Gradle wrapper files so the asset works after copying.
- Keep a simple Kotlin Android app with one `MainActivity`.
- Keep `RokidHudViewportLayout` or an equivalent fixed 3:4 viewport wrapper, because it is the highest-value Rokid-specific part of the starter.
- Remove CameraX, Vosk, microphone, speaker, menu screens, and all permissions.
- Show only a black fullscreen HUD with centered white hello-world text, for example `Hello World`.
- Keep `FLAG_KEEP_SCREEN_ON`.
- Use explicit Kotlin/Android Gradle plugin configuration so the copied project builds cleanly.
- Use package/application id such as `ai.glasskit.hello`
- Validate with:

```bash
cd skills/glasskit/assets/rokid-hello-world
./gradlew :app:assembleDebug
```

## Reference File Plans

### `references/rokid-device-setup.md`

Merge and condense `docs/how-to-get-rokid-glasses.md` plus repeated README run instructions:

- Rokid Glasses and dev cable recommendation.
- Dev cable alternatives and caveat that non-cable APK upload does not provide direct ADB debugging.
- Mac-like setup assumption.
- ADB Wi-Fi setup commands:
  - `adb devices`
  - `adb shell cmd wifi status`
  - `adb shell cmd wifi set-wifi-enabled enabled`
  - `adb shell 'cmd wifi connect-network "NAME" wpa2 "PASSWORD"'`
  - optional `adb tcpip 5555`, `adb connect <IP>`.
- Android Studio run flow.
- Emulator notes from `rokid-feature-demo`: 480x640, density 240, rear camera emulation, mic/camera passthrough limitations.

### `references/rokid-android-patterns.md`

Cover the device and app-layer patterns from `rokid-feature-demo` and the Android clients:

- Hardware assumptions: Android-based glasses, camera, monochrome HUD, mic, speaker, touchpad.
- HUD viewport:
  - 480x640 physical pixels at 240 dpi.
  - Use black background and white text.
  - Use a fixed 3:4 viewport wrapper for phone/emulator rendering.
- Input mapping:
  - Tap/select: `KEYCODE_ENTER` only.
  - Back/cancel: `KEYCODE_BACK`.
  - Swipe forward/back: examples use `KEYCODE_DPAD_DOWN` and `KEYCODE_DPAD_UP`; document existing mapping carefully.
  - Android touchscreen fallback can use single tap, double tap, horizontal fling.
  - Do not copy `KEYCODE_DPAD_CENTER`.
- Permissions and lifecycle:
  - Request only needed permissions.
  - Stop/release media sessions in `onStop`/`onDestroy`.
  - Keep screen on while active.
- CameraX preview snippet:
  - Prefer back/outward camera.
  - Request 1024x768 4:3.
  - Optional 5 fps exact range with fallback.
  - Set target rotation for portrait HUD.
- Microphone/voice command snippet:
  - Vosk grammar-based command recognition for `select`, `back`, `next`, `previous`.
  - Bundle the model under assets only if using voice commands.
  - Use 16 kHz mono `AudioRecord`.
- Speaker snippet:
  - `ToneGenerator(AudioManager.STREAM_MUSIC, 100)` for simple feedback.

### `references/rokid-media-webrtc.md`

Document the Android WebRTC patterns shared across OpenAI, Overshoot, and RF-DETR:

- Dependency: `io.getstream:stream-webrtc-android`.
- Create and dispose `EglBase`, `PeerConnectionFactory`, tracks, capturers, and data channels explicitly.
- Video capture:
  - 1024x768 at 5 fps for low-rate backend detection.
  - 1024x768 at 15 fps for Overshoot.
- Audio:
  - For direct mic to OpenAI, use `JavaAudioDeviceModule`, 16 kHz mono, disable hardware AEC/NS where the example does.
  - For backend-controlled speech playback, use a receive-only audio transceiver.
- Signaling:
  - Create offer, set local description, wait for ICE gathering, POST SDP to backend, normalize answer SDP, set remote description.
  - Use `application/sdp` for direct SDP endpoints, JSON `{ "offer_sdp": "..." }` for Overshoot broker endpoints.
- Data channels:
  - `oai-events` for OpenAI Realtime events.
  - `vision-events` for backend detection/state.
  - Queue outgoing messages until open when needed.
- ICE:
  - STUN for backend/OpenAI flows.
  - Overshoot requires TURN servers at `turn.overshoot.ai` with username/password `overshoot`.

### `references/openai-realtime.md`

Distill the OpenAI Realtime patterns:

- Prefer the Python/FastAPI style from `rokid-overshoot-openai-realtime` for new references; it uses `gpt-realtime-1.5`.
- Explain the backend broker:
  - Android sends SDP offer to backend.
  - Backend POSTs multipart `sdp` and `session` to `https://api.openai.com/v1/realtime/calls`.
  - Backend returns the SDP answer.
  - Backend opens sideband WebSocket at `wss://api.openai.com/v1/realtime?call_id=...`.
- Session config:
  - `type: realtime`
  - `model: gpt-realtime-1.5`
  - set voice as needed, for example `cedar`.
  - add function tools on the backend side when the workflow needs tool calls.
- Patterns:
  - Direct assistant: Android streams mic and possibly camera to OpenAI and renders transcript events.
  - Backend-controlled speech: Android receives audio only; backend sends `Speak exactly this line: ...` and `response.create`.
  - Sideband tool loop: handle `response.done`, find completed function call, send `function_call_output`, optionally `response.create`.
  - Transcript handling: dedupe event IDs, clear stale transcript when `speech_epoch` changes.

### `references/overshoot.md`

Distill the Overshoot live video pattern:

- Backend creates a stream through Overshoot REST:
  - `POST /streams`
  - source type `webrtc` with offer SDP
  - mode `clip`
  - processing config: target fps, clip length, delay
  - inference prompt/model.
- Backend returns `session_id` and answer SDP to Android.
- Android streams camera directly to Overshoot WebRTC using Overshoot TURN servers.
- Backend listens on Overshoot stream WebSocket:
  - Authenticate with API key message.
  - Relay `result` text or structured JSON to Android/control workflow.
  - Keep stream lease alive.
  - Close streams on app stop/disconnect.
- Prompt switching:
  - Patch `/streams/{stream_id}/config/prompt` when changing active detector.
  - Ignore stale results whose prompt/generation does not match the current detector.

### `references/rfdetr.md`

Distill backend object-detection patterns:

- FastAPI plus `aiortc` receives WebRTC video at `/vision/session`.
- Prefer H264 codec when available.
- Use a latest-frame buffer so inference skips stale frames instead of backlogging.
- Use RF-DETR through `inference.get_model`, with `ROBOFLOW_API_KEY` only needed to fetch hosted weights; inference runs locally after download.
- Environment knobs:
  - `RFDETR_MODEL_ID`
  - `RFDETR_CONFIDENCE`
  - `RFDETR_MIN_INTERVAL_S`
  - `RFDETR_FRAME_DIR`
  - `RFDETR_HISTORY_LIMIT`
  - `RFDETR_JPEG_QUALITY`
- Annotate frames with `supervision`, save `latest.jpg` and rolling history.
- Object-triggered HUD pattern:
  - Send config/state over data channel.
  - Use a two-hit confirmation rule before completing a split.
  - Provide manual debug step forward/back controls.
- For Realtime augmentation:
  - Convert latest annotated JPEG to data URI.
  - Insert it as `input_image` after a user audio turn.

### `references/server-authoritative-workflows.md`

Distill the proactive mocktail coach pattern:

- Android should stay thin: HUD rendering, gesture input, permissions, and media links.
- Backend should own session lifecycle, phases, recipe choice, prompt switching, step progression, HUD state, and exact speech.
- Session flow:
  1. Control WebSocket creates a backend session.
  2. User tap sends `session.start`.
  3. Android creates vision and realtime media links.
  4. Backend waits for both links.
  5. Inventory scan stabilizes after two identical normalized ingredient arrays.
  6. Backend selects/activates a recipe.
  7. Backend switches Overshoot detector prompts per step.
  8. Backend evaluates structured results and speaks exact lines through OpenAI Realtime.
  9. Android renders `hud.state` and current transcript.
- Recipe schema:
  - tasks, detectors, steps.
  - detector fields: `ingredients`, `color`, `state`, `flag`, `level`.
  - evaluation modes: `match_value`, `numeric_threshold_with_progress_once`, `count_rising_edges_true`, `enum_progress_once_then_complete`, `momentary_true_complete`.
- HUD state contract:
  - `type`, `screen`, `phase`, `recipe_name`, `tasks`, `active_task_id`, `speech_epoch`.
- Speech contract:
  - Cancel active response before replacing speech.
  - Increment `speech_epoch`.
  - Send exact text via OpenAI sideband.

## Validation Plan

After implementing the skill:

1. Validate skill frontmatter and naming:

```bash
/Users/t/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/glasskit
```

If that local script is unavailable in another environment, manually verify the same rules from `agent-skills.md`.

2. Validate the starter asset:

```bash
cd skills/glasskit/assets/rokid-hello-world
./gradlew :app:assembleDebug
```

4. Check standalone portability:

```bash
rg "\\.\\./\\.\\./|examples/|docs/" skills/glasskit
```

References may mention that content was derived from examples in prose, but should not require paths outside the skill directory.

5. Review `SKILL.md` length and reference index clarity.

## Open Questions

- Should the hello-world template use `ai.glasskit.hello` as the default package/application id, or a neutral `com.example.glasskithello`?
  - => use ai.glasskit.hello
- Should the first skill version document both Node and Python OpenAI Realtime broker patterns, or should it standardize on Python/FastAPI plus `gpt-realtime-1.5` and only mention the Node example as legacy?
  - => use python as sample. but no need to mention node as legacy
- Should the references include short source-file provenance notes for maintainers, or should they avoid all links to repository paths to emphasize standalone portability?
  - avoid all links to repository paths.
