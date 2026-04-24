# Server-Authoritative Workflows

Use this when a Rokid app combines vision, Realtime audio, and multi-step guidance. The core pattern is simple: Android renders and streams; the backend owns decisions.

## Responsibilities

Android owns:

- HUD rendering.
- Rokid key handling.
- Runtime permissions.
- WebRTC links for camera and audio.
- Control WebSocket connection.
- Clearing stale transcript text when `speech_epoch` changes.

Backend owns:

- Session lifecycle.
- Workflow phase transitions.
- Active detector prompt and schema.
- Task progression and completion rules.
- Normalized HUD state.
- Exact speech sent through OpenAI Realtime.

## Session Flow

1. Android opens a control WebSocket, for example `/session/control`.
2. Backend creates a session and sends `session.ready`.
3. User tap sends `session.start`.
4. Android creates required media links, commonly `/session/{session_id}/vision` and `/session/{session_id}/realtime`.
5. Backend waits until required links are ready.
6. Backend collects initial context until a stability rule passes, such as two matching normalized observations.
7. Backend activates a workflow and switches detector prompts for the active task.
8. Backend evaluates structured detector results and advances task state.
9. Backend publishes `hud.state` and sends exact speech lines to OpenAI Realtime.
10. Android renders state and transcript without owning workflow decisions.

## Control Messages

Client to backend:

```json
{ "type": "session.start" }
```

Backend to client:

```json
{
  "type": "hud.state",
  "screen": "running",
  "phase": "ACTIVE",
  "workflow_name": "Demo Workflow",
  "tasks": [
    { "id": "task-1", "text": "Complete the first step", "completed": false }
  ],
  "active_task_id": "task-1",
  "speech_epoch": 3
}
```

Use the app's own phase names, but keep them backend-authored. Android should not infer phase from local timers or transcripts.

## Workflow Schema

Keep workflow data explicit and domain-neutral:

```json
{
  "id": "workflow-id",
  "display_name": "Workflow Name",
  "tasks": [
    {
      "id": "task-1",
      "text": "User-visible task text",
      "detector_id": "detector-1",
      "completion": {
        "mode": "match_value",
        "field": "state",
        "value": "done"
      }
    }
  ],
  "detectors": [
    {
      "id": "detector-1",
      "prompt": "Return compact JSON for the active task.",
      "output_schema": {
        "type": "object",
        "properties": {
          "state": { "type": "string" },
          "flag": { "type": "boolean" },
          "level": { "type": "integer" },
          "confidence": { "type": "number" }
        },
        "additionalProperties": false
      }
    }
  ]
}
```

Useful completion modes:

- `match_value`: complete when a field equals a target value.
- `numeric_threshold_with_progress_once`: publish progress until a threshold is reached once.
- `count_rising_edges_true`: count false-to-true transitions.
- `enum_progress_once_then_complete`: require a sequence of enum states.
- `momentary_true_complete`: complete as soon as a boolean is true.

## Prompt Switching

When switching the active detector:

1. Increment a backend generation number.
2. Patch the vision service prompt/schema.
3. Store the active detector id and generation on the session.
4. Ignore late detector results that do not match the active generation.
5. Publish `hud.state` after state changes.

This avoids stale vision results completing the wrong task.

## Exact Speech Contract

Backend speech should be replaceable and epoch-based:

```python
async def speak_line(session: SessionState, line: str) -> None:
    if session.openai_response_active:
        await send_openai_event(session, {"type": "response.cancel"})
        session.openai_response_active = False

    session.speech_epoch += 1
    await publish_hud_state(session)
    await send_openai_user_text(session, f"Speak exactly this line: {line}")
    await send_openai_event(session, {"type": "response.create"})
```

Android should treat `speech_epoch` as the transcript freshness key. When the epoch changes, clear old partial transcript text before showing new transcript deltas.
