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

```sh
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

```sh
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

```sh
adb devices # confirm your device is visible
adb shell cmd wifi status # see whether it's connected; if not, follow the commands below
adb shell cmd wifi set-wifi-enabled enabled # enable Wi-Fi
adb shell 'cmd wifi connect-network "NAME" wpa2 "PASSWORD"' # connect to the network
adb shell cmd wifi status # confirm the connection
```

Optional wireless ADB:

```sh
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

To view the step IDs, reference images, and criteria in HTML, run `cd backend && uv run scripts/render_origami_steps.py`, then open `backend/debug/origami_steps.html`.

### Recorded-Video Fold-Check Evals

Recorded-video evals make prompt and model changes repeatable without performing every fold again. This project uses [`glasskit eval`](../../cli/README.md) to ask whether each sampled camera frame satisfies an origami step.

The eval suite lives under `backend/eval/`. `adapter.py` is the default adapter for `glasskit eval run` and reuses the live Overshoot fold-check path. `label_adapter.py` uses Gemini to propose draft expectations, while `suggest_criteria.py` and `check_image.py` help investigate and refine step criteria. See the [GlassKit Eval README](../../cli/README.md) for case syntax, command behavior, review controls, filtering, and quality gates.

To use the suite in this project, record a fold-check input video with `ORIGAMI_RECORD_FOLD_CHECK_INPUTS=true`, add or update a case under `backend/eval/cases/`, and point the case at the recording. `backend/eval/cases/full-run.yaml` is the current full-workflow case.

To propose missing expectations with Gemini, set `GEMINI_API_KEY` in `backend/.env` and explicitly select the labeling adapter:

```sh
cd backend
uv run --with-editable ../../../cli --env-file .env \
  glasskit eval seed --case full-run \
  --adapter eval/label_adapter.py:create_evaluator \
  --concurrency 8
```

Review the proposed expectations before treating them as ground truth:

```sh
cd backend
uv run --with-editable ../../../cli glasskit eval review \
  --eval-dir eval \
  --case full-run
```

Run the reviewed suite through the default Overshoot adapter:

```sh
cd backend
uv run --with-editable ../../../cli --env-file .env \
  glasskit eval run --concurrency 2
```

Keep reviewed expectations fixed while changing prompts or criteria. Correct an expectation only when human review shows that the label itself is wrong.

#### Refine Step Criteria

Repeated errors may call for a shared prompt change in `backend/src/fold_check_prompts.py` or a step-specific criteria change in `backend/assets/origami_steps.json`. The project-specific criteria suggester can propose a revision from the target references and reviewed labels:

```sh
cd backend
uv run --env-file .env python -m eval.suggest_criteria \
  --case eval/cases/full-run.yaml \
  --target step_5 \
  --output eval/runs/suggest-criteria/step_5.json
```

The tool writes a proposal without changing `origami_steps.json`. After applying a candidate change, evaluate the target and optionally feed the results into another suggestion pass:

```sh
uv run --with-editable ../../../cli --env-file .env \
  glasskit eval run --concurrency 2 --target step_5 \
  --output-json eval/runs/suggest-criteria/step_5-eval.json
```

If the target still has failures, feed that report back to the criteria suggester:

```sh
uv run --env-file .env python -m eval.suggest_criteria \
  --case eval/cases/full-run.yaml \
  --target step_5 \
  --eval-results eval/runs/suggest-criteria/step_5-eval.json \
  --output eval/runs/suggest-criteria/step_5-feedback.json
```

To investigate individual frames with the same Gemini labeling path used for seeding:

```sh
cd backend
uv run --env-file .env python -m eval.check_image \
  --target step_1 \
  /path/to/frame-38.000s.png \
  /path/to/frame-41.500s.png
```

## Vision Path Comparison

This example uses Overshoot differently from [the drink-making demo](../rokid-overshoot-openai-realtime/README.md).

In this origami app, the Rokid client never connects to Overshoot directly. The glasses publish camera video to the FastAPI backend, and the backend creates an Overshoot stream, publishes the composed camera/reference video into the returned LiveKit room, prompts chat completions against the latest ingested frame, and uses those results to drive the fixed origami workflow.

In the drink-making demo, the glasses stream camera video directly to Overshoot after the backend brokers the connection setup. The backend manages Overshoot prompts and results, but it does not sit in the video path or compose frames.
