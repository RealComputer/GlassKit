# Object Detection

Use this when a Rokid app needs deterministic visual signals from the outward camera: object presence, class labels, bounding boxes, counters, completion triggers, or annotated frames for Realtime augmentation. Keep the detector model interchangeable. RF-DETR is one validated backend, but the app architecture should work with YOLO, a custom local model, a hosted detector, or a task-specific vision service.

Related references:

- `rokid-webrtc.md`: Android camera streaming, SDP signaling, data channels, ICE, and Python `aiortc` receiver setup.
- `openai-realtime.md`: backend-augmented vision, image insertion after user audio turns, and Realtime sideband behavior.
- `server-authoritative-workflows.md`: backend-owned task state, detector prompt/schema switching, HUD state, and exact speech.
- `rokid-inputs.md`: Rokid camera constraints and touchpad/debug controls.

## Architecture

The common object-detection shape is:

1. Android captures a low-rate outward-camera stream.
2. Android sends video to a backend vision endpoint over WebRTC.
3. The backend receives video, runs detection on the latest useful frame, and normalizes model output.
4. The backend publishes app events to Android over a data channel or control WebSocket.
5. The backend optionally stores the latest annotated JPEG for inspection, debugging, or OpenAI Realtime image augmentation.

Android should not interpret raw model envelopes. It should render normalized state such as:

```json
{
  "type": "state",
  "status": "running",
  "detected_classes": ["cup", "plate"],
  "active_task_id": "find-cup",
  "completed_count": 2
}
```

For workflow apps, put task progression on the backend. Android should stream, send user controls, and render HUD state.

## Android Stream

Use a separate camera WebRTC session when detection is not the main Realtime media path. Start with low capture rates; common Rokid values are `1024x768 @ 2 fps` for Realtime augmentation and `1024x768 @ 5 fps` for detection-driven HUDs.

Create local tracks and data channels before creating the offer:

```kotlin
val mediaConstraints = MediaConstraints().apply {
    mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "false"))
    mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "false"))
}

val dataChannel = peerConnection.createDataChannel(
    "vision-events",
    DataChannel.Init()
)
```

Prefer a back/outward camera, then fall back to the first available camera. Match `adaptOutputFormat(...)` and `startCapture(...)` when possible. If the camera HAL rejects the requested mode, start with a supported mode and use `adaptOutputFormat(...)` to cap WebRTC output.

Disable video sender degradation when detection quality matters:

```kotlin
private fun configureVideoSender(sender: RtpSender?) {
    val params = sender?.parameters ?: return
    params.degradationPreference = RtpParameters.DegradationPreference.DISABLED
    sender.parameters = params
}
```

Queue data-channel messages until the channel is open. Send explicit app events such as `session.start`, `run.start`, `debug.step`, or `workflow.confirm` instead of encoding actions as ad hoc key names.

## Backend Receiver

Use FastAPI plus `aiortc` for a backend that terminates the vision WebRTC session:

```python
@app.post("/vision/session")
async def vision_session(request: Request) -> Response:
    offer_sdp = (await request.body()).decode()
    offer = RTCSessionDescription(sdp=offer_sdp, type="offer")

    pc = RTCPeerConnection()
    transceiver = pc.addTransceiver("video", direction="recvonly")
    prefer_video_codec(transceiver, "video/H264")

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        if track.kind == "video":
            asyncio.create_task(vision_processor.consume(track))

    @pc.on("datachannel")
    def on_datachannel(channel: RTCDataChannel) -> None:
        attach_vision_events(channel)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return PlainTextResponse(pc.localDescription.sdp)
```

Close peer connections on `failed`, `closed`, or `disconnected`, and clear data-channel state when the session ends. Prefer H264 when available because it is a good fit for Rokid camera streaming.

## Frame Policy

Object detection should optimize freshness, not throughput. A glasses HUD that reacts to stale frames feels wrong even when inference is accurate.

Use one of these policies:

- **Latest-frame buffer**: keep only the newest frame while inference runs. This works well when the model is slower than the camera stream.
- **Minimum interval**: skip frames until `now - last_processed >= min_interval_s`. This is simple and works well for image augmentation.
- **One in-flight inference**: if a frame is being processed, drop incoming frames instead of building a queue.

Example latest-frame buffer:

```python
class LatestFrameBuffer:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._latest: tuple[int, Any] | None = None
        self._counter = 0
        self._closed = False

    async def update(self, frame: Any) -> None:
        async with self._condition:
            if self._closed:
                return
            self._counter += 1
            self._latest = (self._counter, frame)
            self._condition.notify_all()
```

Run blocking model inference in a worker thread so the media receiver and control channels stay responsive:

```python
image = frame.to_ndarray(format="bgr24")
result = await asyncio.to_thread(run_detection, model, image)
```

Keep model objects warm and reused. Load the model once per process or session, guard lazy initialization with an async lock, and start a warmup task during FastAPI lifespan when startup latency matters.

## Normalized Results

Normalize every detector into a small app-owned structure before any workflow or HUD code sees it:

```python
@dataclass(frozen=True)
class DetectionSnapshot:
    classes: set[str]
    labels: list[str]
    boxes: list[tuple[float, float, float, float]]
    confidences: list[float]
    timestamp: float
    annotated_jpeg: bytes | None = None
```

Keep these rules:

- Map provider labels to domain labels on the backend, for example `"wood panel with label"` to `"BASE PANEL"`.
- Include confidence and timestamp if downstream logic needs stability checks.
- Keep raw predictions available only in logs or debug traces.
- Use stable event types and field names. Android should ignore unknown fields, but it should not need provider-specific parsing.

## Model Backends

Choose the model by the behavior you need:

- Fine-tuned object detector: best for a known set of physical objects, parts, states, or completion markers.
- Open-vocabulary detector: useful during prototyping, but stabilize labels before wiring completion rules to them.
- Hosted detector service: fastest to prototype, but normalize results and hide vendor auth from Android.
- Local exported model: best when latency, cost, offline use, or privacy matter.

Useful generic knobs:

```text
VISION_MODEL_ID
VISION_CONFIDENCE
VISION_MIN_INTERVAL_S
VISION_FRAME_DIR
VISION_HISTORY_LIMIT
VISION_JPEG_QUALITY
```

RF-DETR is a good concrete example. With Roboflow-hosted weights, use `inference.get_model`; `ROBOFLOW_API_KEY` is needed to fetch weights, and inference runs locally after download. Existing RF-DETR examples use knobs such as:

```text
RFDETR_MODEL_ID
RFDETR_CONFIDENCE
RFDETR_MIN_INTERVAL_S
RFDETR_FRAME_DIR
RFDETR_HISTORY_LIMIT
RFDETR_JPEG_QUALITY
```

If you export weights and load them directly with an RF-DETR library, the same architecture applies and `ROBOFLOW_API_KEY` is no longer part of runtime configuration.

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

For multi-step workflows, combine this reference with `server-authoritative-workflows.md`: the backend owns the active detector, completion criteria, HUD state, and speech. Android should not infer progression from local timers, transcripts, or raw detections.

## Event Contracts

Use `vision-events` for vision-only WebRTC data-channel state when that fits the app:

```kotlin
val dataChannel = peerConnection.createDataChannel("vision-events", DataChannel.Init())
```

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

Use a control WebSocket instead when multiple backend services share one session state, when events must outlive one media peer connection, or when the workflow is server-authoritative.

## Annotated Frames

Annotated frames are useful for debugging, model tuning, and Realtime augmentation. Use `supervision`, OpenCV, PIL, or the detector library's own helpers to draw boxes and labels.

Save:

- `latest.jpg` for quick inspection and downstream image augmentation.
- A bounded timestamped history when debugging regressions.

Keep storage bounded with a history limit. A JPEG quality around 85 is a practical default for readable annotations without excessive payload size.

## Realtime Augmentation

For OpenAI Realtime, object detection can provide either structured context or the latest annotated image:

- Use structured text when labels, counts, or state are enough.
- Use an annotated `input_image` when spatial layout, part appearance, or visual ambiguity matters.

Convert the latest annotated JPEG to a data URI:

```python
data_uri = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
```

Insert the image after Realtime has committed the user's audio item, then send exactly one `response.create`. Do not inject images on every event or replay a backlog:

```python
await send_openai_event(
    session,
    {
        "type": "conversation.item.create",
        "previous_item_id": user_audio_item_id,
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": data_uri,
                    "detail": "high",
                }
            ],
        },
    },
)
await send_openai_event(session, {"type": "response.create"})
```

See `openai-realtime.md` for the full event sequence that avoids duplicate image injection.

## Training And Tuning

Train and evaluate from the glasses point of view. Record representative Rokid camera footage, including bad lighting, hand occlusion, motion blur, partial objects, and the distances users actually work at.

Practical tuning loop:

1. Start with a small label set that maps directly to app decisions.
2. Capture annotated frame history while using the app.
3. Review false positives and missed detections from `latest.jpg` plus history frames.
4. Adjust labels, thresholds, and confirmation rules before changing HUD logic.
5. Add manual debug controls so the app remains testable when the detector is wrong.

Keep labels stable once workflow rules depend on them. If the model label names are messy, map them to clean domain names on the backend instead of leaking model names into Android UI or prompts.
