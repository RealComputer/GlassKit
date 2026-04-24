# RF-DETR Object Detection

Use this when running local backend object detection on Rokid camera frames and feeding results back to the HUD, OpenAI Realtime, or another workflow.

## Backend Shape

Use FastAPI and `aiortc` for a WebRTC endpoint:

```python
@app.post("/vision/session")
async def create_vision_session(payload: VisionSessionCreateRequest) -> dict[str, str]:
    answer_sdp = await vision_session_manager.create_session(payload.offer_sdp)
    return {"answer_sdp": answer_sdp}
```

Prefer H264 when available. Receive video into a latest-frame buffer so inference skips stale frames instead of building a queue.

```python
class LatestFrameBuffer:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._latest = None
        self._counter = 0

    async def update(self, frame: Any) -> None:
        async with self._condition:
            self._counter += 1
            self._latest = (self._counter, frame)
            self._condition.notify_all()
```

## Model Setup

Use RF-DETR through `inference.get_model`. `ROBOFLOW_API_KEY` is needed to fetch hosted weights; after download, inference runs locally.

Useful environment knobs:

```text
RFDETR_MODEL_ID
RFDETR_CONFIDENCE
RFDETR_MIN_INTERVAL_S
RFDETR_FRAME_DIR
RFDETR_HISTORY_LIMIT
RFDETR_JPEG_QUALITY
```

Default JPEG quality of 85 is a good balance for annotated frame handoff.

## Annotated Frames

Use `supervision` to annotate detections. Save:

- `latest.jpg` for quick inspection and downstream image augmentation.
- A rolling timestamped history when debugging detection regressions.

Keep frame storage bounded with `RFDETR_HISTORY_LIMIT`.

## Android Data Channel

Use `vision-events` for backend-to-HUD state:

```kotlin
val dataChannel = peerConnection.createDataChannel("vision-events", DataChannel.Init())
```

Typical message types:

- `config`: current detection labels or task metadata.
- `state`: latest detected classes, status, counters, or timers.
- `split_completed` or an app-specific completion event.

Queue outgoing Android messages until the data channel is open. Send explicit app events such as `run.start` or `debug.step` rather than encoding them as key names.

## Object-Triggered HUDs

Use a confirmation rule before changing user-visible state. A two-hit rule works well for glasses demos:

```python
if detected_target:
    consecutive_hits += 1
else:
    consecutive_hits = 0

if consecutive_hits >= 2:
    complete_current_step()
```

Provide manual debug controls on Rokid keys when developing:

- `KEYCODE_DPAD_UP`: advance one internal step.
- `KEYCODE_DPAD_DOWN`: move back one internal step.
- `KEYCODE_ENTER`: start/stop or confirm.

## Realtime Augmentation

To augment OpenAI Realtime with backend vision, convert the latest annotated JPEG to a data URI and insert it after a user audio turn:

```python
data_uri = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()
await send_openai_event(
    session,
    {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Use the current annotated frame."},
                {"type": "input_image", "image_url": data_uri},
            ],
        },
    },
)
```

Send images sparingly; use the latest frame, not a backlog.
