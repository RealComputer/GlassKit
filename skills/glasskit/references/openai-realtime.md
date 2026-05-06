# OpenAI Realtime

OpenAI Realtime is a low-latency, stateful API for speech-to-speech and multimodal sessions. It is a live connection where:

- media moves over a WebRTC peer connection
- user inputs and model outputs are stored as conversation items
- voice activity detection turns completed user speech into model output automatically
  - `response.create` can be used for manual backend-controlled turns, such as tool output, injected images, or workflow-authored speech
- tools, transcripts, lifecycle events, and control messages move as JSON events

Android sends an SDP offer to the backend, the backend creates the Realtime call, and Android receives the SDP answer from the backend.

Use `gpt-realtime-1.5` for new GlassKit Realtime examples. Use the GA Realtime docs and avoid older beta-era examples or model names.

Related reference: `rokid-webrtc.md` covers the Android WebRTC setup, receive-only audio transceivers, SDP normalization, ICE, and lifecycle cleanup that this document assumes.

## How It Works

Think in two planes:

- **Media plane**: Android's WebRTC peer connection carries microphone audio, optional camera media, and remote assistant audio.
- **Control plane**: JSON events move over the `oai-events` WebRTC data channel and a backend WebSocket sideband channel attached to the same Realtime call.

The important objects are:

- **Session**: model, voice, instructions, audio config, tools, turn detection, and output modalities.
- **Conversation item**: a user message, assistant message, tool call, tool output, image input, or audio item in the live conversation.
- **Response**: one model turn. In the default path, Realtime creates the response automatically after VAD decides the user has stopped speaking. Use `response.create` when the app has disabled automatic responses or when the backend adds an item that needs a model answer.
- **Sideband**: a server control channel attached to the call. Use it when backend business logic, tools, workflow state, or guardrails must stay server-side.

### Response Creation

The default pattern is automatic response creation. Leave VAD enabled and let Realtime decide when the user has finished speaking.

Use explicit `response.create` only for backend-gated turns. In that mode, keep VAD enabled for turn detection but set `create_response` to `False`, wait for the completed user turn or backend workflow event, add any required conversation items, and then send exactly one `response.create`.

### Pattern Matrix

| Pattern | Android media into Realtime | Session input config | Response trigger | Backend sideband role |
| --- | --- | --- | --- | --- |
| Direct assistant | Mic audio, optional camera video | `audio.input.turn_detection.type = semantic_vad`; transcription enabled when the client renders user text | Automatic VAD response | Handle tools and optional observability |
| Backend-augmented vision | Mic audio only; camera goes to backend vision service | Same as direct assistant, but `create_response = False` | Backend waits for the committed user audio item, injects image/context, then sends `response.create` | Store latest vision result, inject context, handle tools |
| Output-only backend speech | No mic track; receive-only audio transceiver | Usually omit `audio.input`; configure only output voice | Backend creates text items and sends `response.create` | Own workflow state, cancel/replace speech, handle tools |

## Common Patterns

### Direct Assistant

Use this when the model can own the conversation. Android streams microphone audio and optionally camera media to the Realtime peer connection. Android receives remote assistant audio and renders transcript events from `oai-events`.

This is the simplest pattern for a conversational assistant. The backend still brokers SDP and handles tools so secrets and private data stay off the glasses. Keep automatic turn creation enabled for this pattern.

Session shape:

```python
session_config = {
    "type": "realtime",
    "model": "gpt-realtime-1.5",
    "audio": {
        "input": {
            "noise_reduction": {"type": "near_field"},
            "transcription": {"language": "en", "model": "whisper-1"},
            "turn_detection": {"type": "semantic_vad"},
        },
        "output": {"voice": "marin"},
    },
    "instructions": SESSION_INSTRUCTIONS,
    "tools": [...],
}
```

### Backend-Augmented Vision

Use this when you need to add hints for more reliable spatial understanding, object detection, or domain-specific vision. Android runs two links:

- audio to OpenAI Realtime, brokered by the backend;
- camera video to a backend vision service, such as object detection models.

The backend stores the latest useful frame or structured vision result. After a user audio turn, it can insert an `input_image` or other additional context as an item and then send `response.create`.

Keep VAD, but disable automatic response creation so the backend has time to inject the image or structured vision result before the model answers:

```python
"audio": {
    "input": {
        "noise_reduction": {"type": "near_field"},
        "transcription": {"language": "en", "model": "whisper-1"},
        "turn_detection": {
            "type": "semantic_vad",
            "create_response": False,
            "interrupt_response": False,
        },
    },
}
```

### Backend-Controlled Speech

Use this for server-authoritative workflows where the backend decides each step, client-visible state, and exact spoken line. Use a receive-only audio transceiver on Android so the SDP offer has an audio section, but do not add a microphone track unless the workflow needs user audio in this Realtime session.

For output-only speech, keep the Realtime session small:

```python
session_config = {
    "type": "realtime",
    "model": "gpt-realtime-1.5",
    "audio": {"output": {"voice": "cedar"}},
    "instructions": OPENAI_SESSION_INSTRUCTIONS,
    "tools": [...],
}
```

The backend sends text conversation items such as `Speak exactly this line: ...` followed by `response.create`.

## System Instructions

Realtime instructions should define the assistant's role, speaking style, visual grounding rules, and tool policy. For smart glasses, keep spoken output short, state what to do next, and explicitly handle unclear audio or poor framing. Put workflow authority in the backend when the app has external state, safety constraints, or deterministic step progression.

Example:

```python
SESSION_INSTRUCTIONS = """
# Role
- You are a voice assistant running on smart glasses.
- Help the user complete the current real-world task using speech, tool results, and the latest visual context.

# Speaking Style
- Be concise, concrete, and actionable.
- Use no more than two short sentences per response unless the user asks for detail.
- Do not use sound effects, filler, or stage directions.

# Visual Grounding
- Treat the camera view as the user's current field of view.
- If the image is unclear, blocked, or missing the relevant object, ask the user to adjust their view.
- Do not claim that you can see an object unless the current visual context supports it.

# Tools and Backend State
- Call backend tools for private data, workflow decisions, or external actions.
- Do not invent step progression when the backend owns the workflow state.
- If the user's message starts with `Speak exactly this line:`, speak that line exactly and do not add commentary.
""".strip()
```

Set the same `instructions` field from Python, JavaScript, or any other backend that creates the Realtime session.

## Backend SDP Broker

The backend can be written in any language that can accept SDP and send a multipart request. These are Python/FastAPI snippets.

Endpoint contract:

```python
@app.post("/session/{session_id}/realtime")
async def create_realtime_session(session_id: str, request: Request) -> Response:
    offer_sdp = (await request.body()).decode()
    if not offer_sdp.strip():
        raise HTTPException(status_code=422, detail="offer SDP must not be empty")

    answer_sdp = await session_manager.create_realtime_session(session_id, offer_sdp)
    return Response(content=answer_sdp, media_type="application/sdp")
```

Realtime call creation for backend-gated user audio or vision injection:

```python
session_config = {
    "type": "realtime",
    "model": "gpt-realtime-1.5",
    "audio": {
        "input": {
            "noise_reduction": {"type": "near_field"},
            "transcription": {"language": "en", "model": "whisper-1"},
            "turn_detection": {
                "type": "semantic_vad",
                "create_response": False,
                "interrupt_response": False,
            },
        },
        "output": {"voice": "cedar"},
    },
    "instructions": SESSION_INSTRUCTIONS,
}

form = {
    "sdp": (None, offer_sdp),
    "session": (None, json.dumps(session_config)),
}

upstream = await openai_http.post(
    "https://api.openai.com/v1/realtime/calls",
    headers={"Authorization": f"Bearer {openai_api_key}"},
    files=form,
)
upstream.raise_for_status()

answer_sdp = normalize_sdp(upstream.text)
call_id = upstream.headers["location"].rstrip("/").split("/")[-1]
```

Validate both outputs before returning to Android:

```python
if not call_id or not answer_sdp.startswith("v="):
    raise HTTPException(
        status_code=502,
        detail="OpenAI Realtime response missing call_id or valid answer SDP",
    )
```

Open the sideband after extracting `call_id`:

```python
sideband_url = f"wss://api.openai.com/v1/realtime?call_id={call_id}"
async with websockets.connect(
    sideband_url,
    additional_headers={"Authorization": f"Bearer {openai_api_key}"},
) as openai_sideband:
    async for raw in openai_sideband:
        event = json.loads(raw)
        ...
```

The sideband is the backend's control channel, not the glasses media transport. It can monitor session events, send `session.update`, call tools, insert conversation items, cancel active speech, and create responses.

## Android Client Contract

Use the `oai-events` data channel for Realtime event JSON:

```kotlin
val eventsChannel = peerConnection.createDataChannel(
    "oai-events",
    DataChannel.Init()
)
```

Create data channels, local tracks, and receive-only transceivers before creating the offer. Wait for ICE gathering, POST the full local SDP to the backend, normalize the answer SDP, then set the remote description.

For direct assistant mode:

- add a local microphone audio track;
- add a camera track only for the direct-vision path you have validated;
- set `OfferToReceiveAudio` to `"true"` so assistant speech plays on the device;
- parse `conversation.item.input_audio_transcription.completed` for user text;
- parse `response.output_audio_transcript.done` for final assistant text;
- parse `response.output_audio_transcript.delta` only when rendering live captions.

For output-only backend speech:

- do not add a local microphone track unless the app needs user audio in this Realtime session;
- add a receive-only audio transceiver so the offer has an `m=audio` section;
- require the local SDP to contain `m=audio` before posting it;
- render transcript deltas only for the current speech item;
- clear stale transcript text when backend `speech_epoch` changes.

Deduplicate server events by `event_id` where possible:

```kotlin
private fun shouldIgnoreEvent(json: JSONObject): Boolean {
    val eventId = json.optString("event_id", "")
    if (eventId.isBlank()) return false
    synchronized(seenEventIds) {
        if (seenEventIds.contains(eventId)) return true
        seenEventIds.add(eventId)
    }
    return false
}
```

## Backend-Controlled Speech

Use this pattern when another backend service owns workflow state:

```python
async def speak_line(session: SessionState, text: str) -> None:
    line = text.strip()
    if not line or session.openai_sideband is None:
        return

    if session.openai_response_active:
        await send_openai_event(session, {"type": "response.cancel"})
        session.openai_response_active = False

    session.speech_epoch += 1
    await publish_client_state(session)
    await send_openai_event(
        session,
        {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"Speak exactly this line: {line}",
                    }
                ],
            },
        },
    )
    await send_openai_event(session, {"type": "response.create"})
    session.openai_response_active = True
```

Increment `speech_epoch` or another speech item version before replacing speech. Android should treat that value as the transcript freshness key.

Track active responses from sideband events:

- set `openai_response_active = True` when sending `response.create` or receiving `response.created`;
- set it back to `False` on `response.done`;
- if `response.cancel` returns an error with code `response_cancel_not_active`, treat it as benign and clear the flag.

## Tool Loop

Keep tools on the backend. The sideband receives the same Realtime events as the client, including completed function calls. Handle tool calls from `response.done`, send a function output item, then continue only when the model should keep reasoning or speaking from that output.

Intermediate tools usually continue. Terminal tools should not. For example, `list_recipes` continues so the model can call `activate_recipe`; `activate_recipe` does not continue because the backend activates the recipe and speaks exact workflow lines itself.

```python
async def send_tool_output(
    session: SessionState,
    *,
    call_id: str,
    result: object,
    continue_response: bool,
) -> None:
    await send_openai_event(
        session,
        {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result),
            },
        },
    )
    if continue_response:
        await send_openai_event(session, {"type": "response.create"})
```

## Image Injection

For backend vision augmentation, insert the latest frame after Realtime has committed and added the user's audio item, then create the response.

Use the event sequence from the RF-DETR example:

1. On `input_audio_buffer.committed`, store the `item_id` as a pending user turn.
2. On `conversation.item.added`, check that the item id is pending and that the item is a user message containing `input_audio`.
3. Insert the latest `input_image` with `previous_item_id` set to that audio item id.
4. Send exactly one `response.create`.

Do not inject on every `conversation.item.added`; tool outputs, image items, and assistant items can also appear there.

```python
pending_turns: set[str] = set()
sent_images: set[str] = set()

if event["type"] == "input_audio_buffer.committed":
    pending_turns.add(event["item_id"])

if event["type"] == "conversation.item.added":
    item = event["item"]
    item_id = item["id"]
    if item_id in pending_turns and item_id not in sent_images:
        pending_turns.discard(item_id)
        if _is_user_audio_item(item):
            sent_images.add(item_id)
            await send_latest_frame(openai_sideband, item_id)

def _is_user_audio_item(item) -> bool:
    if item.get("type") != "message" or item.get("role") != "user":
        return False
    content = item.get("content") or []
    return any(part.get("type") == "input_audio" for part in content)
```

```python
await send_openai_event(
    session,
    {
        "type": "conversation.item.create",
        "previous_item_id": user_item_id,
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": latest_frame_data_uri,
                    "detail": "high",
                }
            ],
        },
    },
)
await send_openai_event(session, {"type": "response.create"})
```
