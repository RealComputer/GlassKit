# Object Detection

Object detection on Rokid Glasses and similar camera glasses is most useful when the app needs deterministic visual signals from the outward camera: object presence, class labels, bounding boxes, counters, completion triggers, structured context, or annotated frames for realtime model augmentation. The output may drive visible UI, speech, logs, controls, or backend workflow state.

Related references:

- `rokid-webrtc.md`: Android camera streaming, SDP signaling, data channels, ICE, and Python `aiortc` receiver setup.
- `openai-realtime.md`: provider-specific realtime model wiring for backend-augmented vision, image insertion after user audio turns, sideband events, and transcripts.
- `rokid-inputs.md`: Rokid camera constraints and touchpad/debug controls.

## Architecture

The common object-detection shape is:

1. Android captures a low-rate outward-camera stream.
2. Android sends video to a backend vision endpoint over WebRTC.
3. The backend receives video, runs detection on the latest useful frame, and normalizes model output.
4. The backend publishes app events to Android over a data channel or control WebSocket.
5. The backend optionally stores the latest annotated JPEG for inspection, debugging, or realtime model image augmentation.

Android should not interpret raw model envelopes. It should consume normalized app state such as:

```json
{
  "type": "state",
  "status": "running",
  "detected_classes": ["cup", "plate"],
  "active_task_id": "find-cup",
  "completed_count": 2
}
```

For workflow apps, put task progression on the backend. Android should stream, send user controls, and render or act on normalized state.

## Android Stream

Use a separate camera WebRTC session when detection is not the main realtime media path. Start with the lowest resolution and frame rate that still supports the detector. A known working Rokid baseline is `1024x768 @ 5 fps`; raise resolution or frame rate only when the detector needs it. For glasses apps, freshness and stability usually matter more than visual smoothness.

Prefer the outward-facing camera. If the requested mode is not supported by the camera HAL, start capture with a supported mode and let WebRTC adapt the outgoing stream. Create any data channel before the offer if detection events need to move over the same peer connection.

Send explicit app events such as `session.start`, `run.start`, `debug.step`, or `workflow.confirm`. Queue client events until the channel or control socket is open.

## Backend Receiver

The backend can be any stack that can receive media and run inference. In Python, use `aiortc` for WebRTC termination instead of hand-rolled SDP or media parsing. See `rokid-webrtc.md` for the receiver shape.

Keep the receiver thin: accept the media stream, hand frames to a vision processor, and publish normalized app events. Keep session lifecycle, cleanup, and state broadcasting outside the detector model wrapper so the model can be swapped later.

Close peer connections on failed, closed, or disconnected states, and clear channel/session state when the stream ends. If the app supports only one active vision stream, close existing peer connections and clear channel/session state before accepting a new offer so stale detections cannot affect the next run. Prefer H264 when available because it is a practical codec choice for Rokid camera streaming.

## Frame Policy

Object detection should optimize freshness, not throughput. A camera-glasses app that reacts to stale frames feels wrong even when inference is accurate.

Use one of these policies:

- **Latest-frame buffer**: keep only the newest frame while inference runs. This works well when the model is slower than the camera stream.
- **Minimum interval**: skip frames until `now - last_processed >= min_interval_s`. This is simple and works well for image augmentation.
- **One in-flight inference**: if a frame is being processed, drop incoming frames instead of building a queue.

Run blocking model inference outside the event loop so media receiving and control messages stay responsive. Keep model objects warm and reused; repeated per-frame model loading will dominate latency and make the interaction unusable.

## Normalized Results

Normalize every detector into a small app-owned structure before any workflow or client code sees it:

```python
@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float | None
    box_xyxy: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class DetectionSnapshot:
    detections: list[Detection]
    classes: set[str]
    image_size: tuple[int, int] | None
    timestamp: float
    annotated_jpeg: bytes | None = None
```

Keep these rules:

- Map provider labels to domain labels on the backend.
- Include confidence and timestamp if downstream logic needs stability checks.
- Make the bounding-box convention explicit. `box_xyxy` should mean left, top, right, bottom in source-image pixels; use a `_norm` suffix or a `coordinate_space` field for normalized boxes.
- Prefer a list of detection objects over parallel `labels`, `boxes`, and `confidences` arrays unless the app already has a strict schema for parallel arrays.
- Keep raw predictions available only in logs or debug traces.
- Use stable event types and field names. Android should ignore unknown fields, but it should not need provider-specific parsing.

## Model Backends

Choose the model by the behavior you need:

- Fine-tuned object detector: best for a known set of physical objects, parts, states, or completion markers.
- Open-vocabulary detector: useful during prototyping, but stabilize labels before wiring completion rules to them.
- Hosted detector service: fastest to prototype, but normalize results and hide vendor auth from Android.
- Local exported model: best when latency, cost, offline use, or privacy matter.

RF-DETR is a good concrete example for fine-tuned object detection. With Roboflow-hosted weights, the API key is only needed for weight access; inference can run locally after the model is available. If you export weights and load them directly, the same app architecture applies without a hosted weight dependency.

## Decision Logic

Do not let a single detection immediately mutate important user-visible state unless the workflow truly tolerates false positives. Add a confirmation rule between normalized detections and app state.

A two-hit rule works well for simple glasses demos:

```python
if target_class in snapshot.classes:
    consecutive_hits += 1
else:
    consecutive_hits = 0

if consecutive_hits >= 2:
    complete_current_step()
```

Other useful rules:

- Presence over time: require a class to appear for N frames or M milliseconds.
- Rising edge count: count false-to-true transitions, useful for repeated actions.
- Best-confidence match: choose the highest-confidence object among allowed labels.
- Region rule: require the object box to be inside a known image region.
- Generation match: ignore detector results from an old task generation after the backend switches tasks.

For multi-step workflows, the backend should own the active detector, completion criteria, client-visible state, backend actions, and any workflow speech. Android should not infer progression from local timers, transcripts, or raw detections.

## Event Contracts

Use a stable channel or socket contract for vision state. A WebRTC data channel such as `vision-events` is a good fit when the camera peer connection already exists and events only matter while that stream is live.

Common backend-to-Android events:

- `config`: detector labels, workflow steps, or task metadata.
- `state`: normalized status, active task, counters, and latest detection summary.
- `detection`: optional debug-only detection snapshot.
- Domain event, such as `split_completed`, `task.completed`, or `workflow.done`.

Common Android-to-backend events:

- `session.start` or `run.start`.
- `debug.step` with a direction or target id.
- `workflow.confirm` for explicit user confirmation.
- `session.stop` when the app exits.

Use a control WebSocket instead when multiple backend services share one session state, when events must outlive one media peer connection, or when the backend owns long-lived workflow state.

## Annotated Frames

Annotated frames are useful for debugging, model tuning, and realtime model augmentation. Use `supervision`, OpenCV, PIL, or the detector library's own helpers to draw boxes and labels.

Save:

- `latest.jpg` for quick inspection and downstream image augmentation.
- A bounded timestamped history when debugging regressions.

Keep storage bounded with a history limit. A JPEG quality around 85 is a practical default for readable annotations without excessive payload size.

## Realtime Model Augmentation

Object detection can provide either structured context or the latest annotated image to a realtime model:

- Use structured text when labels, counts, or state are enough.
- Use an annotated `input_image` when spatial layout, part appearance, or visual ambiguity matters.

Convert the latest annotated JPEG to a data URI:

```python
data_uri = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
```

Insert the image after the realtime session has committed the user's audio turn, then request exactly one model response. Do not inject images on every event or replay a backlog.

When wiring the trigger, keep a per-turn gate: wait for the user audio turn to be committed, verify that the committed turn belongs to the user, and attach the image only once for that turn. The exact event names are provider-specific; this is the final action in pseudocode:

```python
await realtime_session.add_user_image(
    image_url=data_uri,
    after_turn_id=user_audio_turn_id,
    detail="high",
)
await realtime_session.create_response()
```

See `openai-realtime.md` for one concrete event sequence that avoids duplicate image injection.

## Training And Tuning

Train and evaluate from the glasses point of view. Record representative Rokid camera footage, including bad lighting, hand occlusion, motion blur, partial objects, and the distances users actually work at.

Practical tuning loop:

1. Start with a small label set that maps directly to app decisions.
2. Capture annotated frame history while using the app.
3. Review false positives and missed detections from `latest.jpg` plus history frames.
4. Adjust labels, thresholds, and confirmation rules before changing client or workflow logic.
5. Add manual debug controls so the app remains testable when the detector is wrong.

Keep labels stable once workflow rules depend on them. If the model label names are messy, map them to clean domain names on the backend instead of leaking model names into Android UI or prompts.
