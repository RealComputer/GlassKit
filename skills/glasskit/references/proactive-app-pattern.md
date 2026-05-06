# Proactive App Pattern

Proactive glasses apps continuously observe real-world context and react when something meaningful changes. They are not just chat flows waiting for user prompts. The main design problem is turning noisy perception into reliable app events.

Use this pattern when camera, audio, sensor, or backend observations should guide, alert, adapt, or trigger actions without requiring an explicit command for every step.

Related references:

- `rokid-webrtc.md`: media streaming and data channel setup.
- `openai-realtime.md`: realtime model turns, backend-controlled speech, and sideband control.
- `object-detection.md`: detector events, confirmation rules, and detection-driven task progression.

## Core Loop

```text
camera/audio/sensors
  -> perception loop
  -> normalized observation
  -> stabilization or trigger policy
  -> app workflow/controller
  -> wearer feedback or action
```

Feedback can be visual display, audio, haptics if available, logs, or backend actions. The proactive pattern does not require any one output channel.

## Perception Loop

The perception loop can use any provider that turns live context into observations:

- continuous VLM inference, such as Overshoot
- object detection
- OCR
- barcode or marker detection
- hand, pose, or gesture detection
- periodic image turns to a realtime model
- audio events, sensors, or backend events

Overshoot is useful for this shape because it can run continuous VLM inference over a live WebRTC stream and return structured results. Treat it as one possible perception provider behind the same observation contract, not as a requirement of the architecture.

## Observation Contract

Normalize provider output before app logic sees it. Avoid letting raw VLM text, detector envelopes, transcripts, or provider-specific schemas directly drive behavior.

Prefer small app-owned events:

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

The contract should make stale-result checks possible. Include a generation, active task id, prompt id, detector id, or equivalent field when the perception request changes over time.

## Stabilization

Continuous inference is noisy. Define the trigger policy between observations and app behavior.

Useful rules include:

- require the same normalized result for N consecutive observations
- require a condition to hold for M milliseconds
- count rising edges instead of every positive frame
- require confidence or agreement across providers
- require explicit user confirmation for important actions
- ignore observations whose generation, task id, prompt, or detector does not match the active request

Do not emit user-facing feedback or external actions on every inference callback unless the app explicitly needs a live debug stream.

## Workflow Authority

Workflow authority means one controller owns the current app state, active perception request, and effect of each observation. In networked glasses apps this is usually the backend. In fully local apps it can be an on-device controller.

For each state, define:

- the active perception query
- the observation schema accepted in that state
- the trigger or stabilization rule
- the transition, feedback, or action caused by a valid observation
- how old perception results are invalidated when the state changes

This prevents raw model responses, client timers, transcripts, and disconnected services from independently advancing the app.

## Avoid

- raw model or provider output directly mutates app state
- a single noisy observation triggers an important action
- feedback is emitted on every inference result
- old perception results remain valid after the active task changes
- multiple components mutate the same workflow state independently

## Example

A concrete example of this pattern is the proactive drink-making coach in GlassKit:

https://github.com/RealComputer/GlassKit/tree/main/examples/rokid-overshoot-openai-realtime

That example uses Overshoot for the continuous VLM loop and OpenAI Realtime for spoken guidance, but the pattern generalizes to other perception providers and workflow domains.
