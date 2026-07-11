# Example: Origami Guide (Rokid Glasses/Overshoot)

This app guides Rokid Glasses wearers through origami folds. The HUD shows folding reference images, and the backend proactively checks each fold with Overshoot.

For demo purposes, the app includes a browser demo page that simulates what the wearer sees through the glasses and provides app controls.

It uses [Overshoot](https://overshoot.ai/) for live visual understanding.

## What the App Does

- Shows a visual reference for each origami folding step on the Rokid HUD
- Checks the current fold with Overshoot and advances through the fixed workflow
  - The camera input stream is composed with a reference origami state image, then sent to a VLM to check whether the fold step is complete.
- Controls:
  - Supports swiping forward/backward for manual step navigation
  - Uses a double tap to start from the start screen and reset while a session is running or completed
- Lets the browser demo view the composed camera/HUD feed and send controls, including toggling auto check when available

## Development

See also [AGENTS.md](./AGENTS.md) for technical details.

### Requirements

- [Rokid Glasses + dev cable](../../docs/how-to-get-rokid-glasses.md)
- `adb` for Android
- `uv` for Python
- Overshoot API key (`OVERSHOOT_API_KEY`)

### Configuration

Set the backend URL in `rokid/local.properties`:

```properties
BACKEND_BASE_URL=http://<YOUR_BACKEND>:8000
```

Create the backend environment file:

```bash
cd backend
cp .env.example .env
# set OVERSHOOT_API_KEY
```

Optional backend overrides can also be specified inline when starting FastAPI:

- `ORIGAMI_AUTO_CHECK_ENABLED=false` to keep sessions and the browser demo running without opening fold-check provider streams. When disabled at startup, auto check stays off.
- `ORIGAMI_RECORD_FOLD_CHECK_INPUTS=false` to disable the default recording of real camera frames sent into the fold-check path for inspection. Recordings are written under `backend/debug/fold-check-inputs` before reference-image composition.
- `ORIGAMI_FOLD_CHECK_INPUT_RECORDING_DIR` to choose where fold-check input recordings are written
- `ORIGAMI_DEBUG_SAVE_FOLD_CHECK_COMPOSITES=true` to save fold-check input previews for debugging
- `ORIGAMI_DEBUG_FOLD_CHECK_COMPOSITE_DIR` to choose where debug preview images are written
- `OVERSHOOT_MODEL`

### Run the Backend

```bash
cd backend
uv run --env-file .env fastapi dev src/main.py --host 0.0.0.0
```

Open the browser demo:

```text
http://<YOUR_BACKEND>:8000/demo
```

### Run the Glasses App

Connect Rokid Glasses to your computer using the dev cable, enable Wi-Fi via ADB (see below), then install and run the app via `adb`.

Useful ADB commands:

```bash
adb devices # confirm your device is visible
adb shell cmd wifi status # see whether it's connected; if not, follow the commands below
adb shell cmd wifi set-wifi-enabled enabled # enable Wi-Fi
adb shell 'cmd wifi connect-network "NAME" wpa2 "PASSWORD"' # connect to the network
adb shell cmd wifi status # confirm the connection
```

Optional wireless ADB:

```bash
adb shell ip -f inet addr show wlan0 # check the glasses IP
ping -c 5 -W 3 <IP> # check connectivity (the first ping may time out)
adb tcpip 5555 # enable remote ADB mode
adb connect <IP> # connect to the glasses over remote ADB
adb devices # verify the remote connection (you can unplug the cable afterward)
```

### Assets

- Rokid HUD step images: `rokid/app/src/main/res/drawable-nodpi/origami_step_*.png`
- Backend demo HUD step images: `backend/assets/step-imgs/origami_step_*.png`

The two step-image sets are identical copies kept in both locations because Android resources and backend demo assets load from separate trees.

- Backend reference images: `backend/assets/ref-imgs/*.jpg`
- Step config and per-step prompts: `backend/assets/origami_steps.json`

### Recorded-Video Fold-Check Evals

Testing this app only by wearing the glasses is slow: every prompt, model, or workflow change can require repeating the same physical folds. A recorded-video eval turns that manual check into a repeatable test. You record a run once, label what the fold checker should answer at specific times, and replay those checks with [`glasskit eval`](../../cli/README.md).

In this project, the eval answers one question for each sampled video frame: should the current origami step be considered complete? The `glasskit eval` CLI loads the video and the YAML labels, calls this repo's adapter in `backend/eval/adapter.py`, and reports whether the adapter's result matched the expected value. The adapter reuses the live backend's fold-check composition, prompt, Overshoot chat-completion, and parsing helpers: it composes the camera frame with the step reference image, sends that composed frame to Overshoot, parses the VLM response, and returns `true` or `false`.

The eval files live under `backend/eval/`:

- `adapter.py` connects `glasskit eval` to the origami fold-check logic.
- `check_image.py` checks one or more camera images against an origami step with the same Gemini labeling path as case generation.
- `plans/*.yaml` are small label plans used to generate eval cases from recordings.
- `generate_case.py` asks Gemini to pre-label planned timestamp ranges with a smarter model and writes the first draft of a case.
- `cases/*.yaml` are the runnable eval cases. Each case points to a recording, chooses timestamps or ranges to sample, and declares the expected result for each step.

To create a new eval, first record fold-check input video from the backend with `ORIGAMI_RECORD_FOLD_CHECK_INPUTS=true`. You can move the recording wherever you keep eval media.

You can write the case YAML by hand, but generating a draft with a larger VLM is convenient. This works because the live app needs a fast model so the wearer gets instant feedback, but case generation is not in the user loop; it can spend more time per frame and use a smarter, slower model to draft labels. Start with a label plan that names the recording, sampling interval, and timestamp ranges to label for each target. For example, `backend/eval/plans/full-run.yaml`:

```yaml
video: ../../../../../../GlassKit_origami-recordings/full-run.mp4
sampling:
  every_s: 0.5
targets:
  step_1:
    range: [0.0, 51.0]
  step_2:
    ranges:
    - [52.0, 64.0]
    - [70.0, 82.5]
```

The plan's `video:` path is resolved relative to the plan YAML file. Before running the generator, add `GEMINI_API_KEY` to `backend/.env`.

Generate a new case YAML:

```bash
cd backend
uv run --env-file .env python -m eval.generate_case \
  --plan eval/plans/full-run.yaml \
  --output eval/cases/full-run.yaml
```

The generator calls Gemini with the same fold-check prompt shape used by the runtime path and samples frames from the requested ranges. It writes a case YAML to `--output`. Review and fix the generated YAML before committing it. The reviewed case file is what `glasskit eval` runs.

To check individual camera images while reviewing labels, pass the target step followed by one or more image paths:

```bash
cd backend
uv run --env-file .env python -m eval.check_image \
  --target step_1 \
  /path/to/frame-38.000s.png \
  /path/to/frame-41.500s.png
```

The checker composes each image with the target's reference image and prints Gemini's boolean result.

Here is what the case YAML looks like. A minimal case says which video to replay and what each step should return:

```yaml
video: ../../../../../../GlassKit_origami-recordings/full-run.mp4
targets:
  step_1:
    samples:
    - range: [0.0, 21.0]
      expect: false
    - range: [21.0, 51.0]
      expect: true
  step_2:
    ...
```

In this example, frames from 0.0s up to 21.0s are expected to return `false`; frames from 21.0s up to 51.0s are expected to return `true`.

Run evals locally from `backend/` with the default CLI options:

```bash
cd backend
uv run --with glasskit.ai --env-file .env glasskit eval run
```

The command prints case progress, per-target results, and a final summary. You can use these results to improve the app and aim for a higher score.

## Vision Path Comparison

This example uses Overshoot differently from [the drink-making demo](../rokid-overshoot-openai-realtime/README.md).

In this origami app, the Rokid client never connects to Overshoot directly. The glasses publish camera video to the FastAPI backend, and the backend creates an Overshoot stream, publishes the composed camera/reference video into the returned LiveKit room, prompts chat completions against the latest ingested frame, and uses those results to drive the fixed origami workflow.

In the drink-making demo, the glasses stream camera video directly to Overshoot after the backend brokers the connection setup. The backend manages Overshoot prompts and results, but it does not sit in the video path or compose frames.
