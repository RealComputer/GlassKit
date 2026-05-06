# Proactive App Pattern

Proactive glasses apps are workflow apps driven by continuous observations. They should feel less like a chat assistant waiting for prompts and more like a task partner that notices relevant state changes, updates the HUD, and speaks only when the workflow calls for it.

Use this pattern when the app should react to the user's real-world context without requiring an explicit voice or touch command for every step.

Related references:

- `rokid-webrtc.md`: camera, microphone, data channel, and backend media-session setup.
- `openai-realtime.md`: backend-controlled speech, sideband control, transcripts, and realtime model turns.
- `object-detection.md`: normalized detector events, confirmation rules, and detection-driven task progression.

## Core Shape

Keep Android thin and make the backend the workflow authority:

```text
Android media/control loops
  -> backend session runtime
    -> continuous perception loop
    -> observation normalizer/stabilizer
    -> workflow state machine
    -> HUD, speech, and action publisher
```

Android should:

- capture and stream camera/audio at the lowest useful rate
- render normalized HUD state
- send explicit user controls such as `session.start`, `session.stop`, `debug.step`, or `workflow.confirm`
- keep local UI responsive during backend reconnects and media-session restarts

The backend should:

- own session lifecycle, task phase, active prompt or detector, and step progression
- normalize raw perception output before workflow code sees it
- stabilize noisy observations before mutating user-visible state
- publish compact state to the HUD
- decide when to speak, cancel, replace, or suppress speech
- discard stale results from old generations after prompts, detectors, or media sessions change

## Perception Loop

The perception loop can be implemented with any service or model that produces useful observations from the camera stream:

- continuous VLM inference, such as Overshoot
- object detection
- OCR
- barcode or marker detection
- hand, pose, or gesture detection
- periodic image turns to a realtime model
- non-visual sensors or backend events

Overshoot is a useful service for this shape because it can run continuous VLM inference over a live WebRTC stream and return structured results. Do not design the app so that only Overshoot can fit the architecture. Treat it as one possible perception provider behind the same observation contract.

Raw provider output should be converted into app-owned observations. Prefer small structured payloads over provider envelopes or free text:

```json
{
  "type": "observation",
  "generation": 4,
  "source": "vision",
  "task_id": "find-ingredient",
  "value": {
    "visible_items": ["lime", "cup"],
    "ready": true
  }
}
```

## Stabilization

Continuous inference is noisy. Put a confirmation rule between observations and workflow transitions unless the workflow tolerates false positives.

Useful rules include:

- require the same normalized result for N consecutive observations
- require a condition to hold for M milliseconds
- count rising edges instead of every positive frame
- require confidence or agreement across providers
- require explicit user confirmation for important actions
- ignore observations whose `generation`, `task_id`, prompt, or detector does not match the active workflow state

The user should not hear a new instruction for every inference result. Speech should come from workflow transitions, notable corrections, or deliberate status updates.

## Workflow Authority

Workflow authority means one backend component decides what state the app is in and what external behavior follows from that state. It should not be split across Android UI code, raw model responses, transcripts, and timers.

For each phase or step, define:

- the active prompt, detector, or perception query
- the observation schema the workflow accepts
- the stabilization rule
- the condition that advances, retries, corrects, or fails the step
- the HUD state to publish
- the exact speech or model turn to trigger
- cleanup behavior when the session stops or restarts

A compact event loop is usually easier to reason about than scattered callbacks:

```text
receive event
  -> reject stale event
  -> normalize event
  -> update phase-local runtime state
  -> maybe transition workflow
  -> publish HUD state
  -> maybe speak or trigger model turn
```

Use realtime models as collaborators, not as the only state holder, when the app has deterministic progression, safety constraints, or external state. The model can choose among backend-provided options, explain the next action, or speak an authored line, but the backend should still own step completion and client-visible state.

## Output

Treat HUD state and speech as separate outputs from the same workflow state.

HUD state should be compact and replaceable:

```json
{
  "type": "state",
  "phase": "guiding",
  "title": "Add lime",
  "body": "Squeeze the lime into the cup.",
  "status": "watching"
}
```

Speech should be sparse and cancellable. Track an epoch, response id, or generation for active speech so a newer workflow transition can replace stale output. Avoid long narration; smart-glasses speech should be short, concrete, and actionable.

## Failure Modes

Avoid these patterns:

- Android interprets raw VLM, detector, or LLM envelopes.
- A single positive observation completes an important step.
- The app speaks on every inference callback.
- Model transcripts or local timers advance a workflow the backend owns.
- Prompt changes do not invalidate older perception results.
- Multiple services mutate session state independently.
- HUD state and spoken state drift because they come from different authorities.

## Example

A concrete example of this pattern is the proactive drink-making coach in GlassKit:

https://github.com/RealComputer/GlassKit/tree/main/examples/rokid-overshoot-openai-realtime

That example uses Overshoot for the continuous VLM loop and OpenAI Realtime for spoken guidance, but the pattern generalizes to other perception providers and workflow domains.
