# OpenAI Realtime

OpenAI Realtime is a low-latency, stateful API for speech-to-speech and multimodal sessions. It is a live connection where:

- media moves over a WebRTC peer connection
- user inputs and model outputs are stored as conversation items
- voice activity detection turns completed user speech into model output automatically
  - `response.create` can be used for manual backend-controlled turns, such as tool output, injected images, or workflow-authored speech
- tools, transcripts, lifecycle events, and control messages move as JSON events

Android sends an SDP offer to the backend, the backend creates the Realtime call, and Android receives the SDP answer from the backend.

`gpt-realtime-1.5` is the latest Realtime model. Use the GA Realtime docs and avoid older beta-era examples or model names.

Related reference: `rokid-webrtc.md` covers the Android WebRTC setup, receive-only audio transceivers, SDP normalization, ICE, and lifecycle cleanup that this document assumes.

## How It Works

Think in two planes:

- **Media plane**: Android's WebRTC peer connection carries microphone audio, optional direct camera media, and remote assistant audio.
- **Control plane**: JSON events move over the `oai-events` WebRTC data channel and a backend WebSocket sideband channel attached to the same Realtime call.

The important objects are:

- **Session**: model, voice, instructions, audio config, tools, turn detection, and output modalities.
- **Conversation item**: a user message, assistant message, tool call, tool output, image input, or audio item in the live conversation.
- **Response**: one model turn. In the default path, Realtime creates the response automatically after VAD decides the user has stopped speaking. Use `response.create` when the app has disabled automatic responses or when the backend adds an item that needs a model answer.
- **Sideband**: a server control channel attached to the call. Use it when backend business logic, tools, workflow state, or guardrails must stay server-side.

### Response Creation

The default pattern is automatic response creation. Leave VAD enabled and let Realtime decide when the user has finished speaking.

Use explicit `response.create` only for backend-gated turns. In that mode, keep VAD enabled for turn detection but set `create_response` to `False`, wait for the completed user turn or backend workflow event, add any required conversation items, and then send exactly one `response.create`.

## Common Patterns

| Pattern | Media links | Response creation | Use when |
| --- | --- | --- | --- |
| Direct assistant | Mic, optional direct camera media, assistant audio over one Realtime WebRTC call | Automatic VAD responses | The model can own the conversation and tools are enough backend logic |
| Backend-augmented vision | Mic and assistant audio over Realtime; camera to backend vision service | Backend sends `response.create` after injecting visual context | You need object detection, spatial hints, annotated frames, or domain-specific vision |
| Server-authoritative speech | Assistant audio over Realtime; workflow state over backend control socket; optional separate vision link | Backend sends exact speech items and `response.create` | Backend owns state transitions, timing, guardrails, or deterministic workflow progress |

### Direct Assistant

Use this when the model can own the conversation. Android streams microphone audio and, for the confirmed-working direct vision path, camera media to the Realtime peer connection. Android receives remote assistant audio and renders transcript events from `oai-events`.

This is the simplest pattern for a conversational assistant. The backend still brokers SDP and handles tools so secrets and private data stay off the glasses. Keep automatic turn creation enabled for this pattern.

Direct assistant session shape:

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
        "turn_detection": {
            "type": "semantic_vad",
            "create_response": False,
            "interrupt_response": False,
        },
    },
}
```

The backend sideband should wait for a committed user audio item, wait for that same item to appear as a conversation item, insert the latest frame after it, then create the response. If no frame is available, still send `response.create` so the user turn does not stall.

### Backend-Controlled Speech

Use this for server-authoritative workflows where the backend decides each step, client-visible state, and exact spoken line. If this Realtime session does not need user microphone audio, do not add a local microphone track; create a receive-only audio offer so the assistant can speak. If the session does include user audio but the backend must gate each turn, disable automatic response creation.

The backend sends text conversation items such as `Speak exactly this line: ...` followed by `response.create`. Track active responses with `response.created`, `response.done`, and `error` events so replacement speech can cancel any currently active response before starting the next one.

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

Realtime call creation for backend-gated audio turns or vision injection:

```python
session_config = {
    "type": "realtime",
    "model": "gpt-realtime-1.5",
    "audio": {
        "input": {
            "turn_detection": {
                "type": "semantic_vad",
                "create_response": False,
                "interrupt_response": False,
            },
        },
        "output": {"voice": "cedar"},
    },
    "instructions": (
        "When the user's message starts with `Speak exactly this line:`, "
        "speak that line exactly."
    ),
    # Optional. Keep private tools on the backend sideband.
    "tools": [...],
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

For receive-only backend-controlled speech, omit `audio.input` unless this Realtime call also carries user microphone audio. The server can still create text conversation items and trigger spoken output with `response.create`.

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
        event = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        ...
```

The sideband is the backend's control channel, not the glasses media transport. It can monitor session events, send `session.update`, call tools, insert conversation items, cancel active speech, and create responses.

### Sideband Lifecycle

Treat sideband state as session runtime state, not global process state:

- increment a realtime generation before replacing or closing a Realtime call;
- close the previous sideband WebSocket before attaching a new one;
- store the `call_id` and sideband WebSocket only if the session is still current;
- mark Realtime ready only after the sideband WebSocket has connected;
- clear `openai_response_active`, `openai_ws`, `openai_call_id`, and readiness on close;
- ignore events from stale generations.

Minimal event handling:

```python
async for raw in openai_sideband:
    event = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    event_type = event.get("type")

    if event_type == "response.created":
        session.openai_response_active = True
        continue

    if event_type == "response.done":
        session.openai_response_active = False
        await handle_response_done(session, event.get("response") or {})
        continue

    if event_type == "error":
        error = event.get("error") or {}
        if error.get("code") == "response_cancel_not_active":
            session.openai_response_active = False
            continue
        await fail_or_recover(session, error)
```

It is also fine to set `openai_response_active = True` optimistically when sending `response.create`, then reconcile with `response.created`, `response.done`, and `error`.

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
- parse `response.output_audio_transcript.delta` and `response.output_audio_transcript.done` for assistant transcript.

For backend-controlled speech:

- do not add a local microphone track unless the app needs user audio in this Realtime session;
- add a receive-only audio transceiver so the offer has an `m=audio` section;
- require the local SDP to contain `m=audio` before posting it;
- render transcript deltas only for the current speech item;
- clear stale transcript text when backend `speech_epoch` changes.

Receive-only audio offer:

```kotlin
private fun addReceiveOnlyAudioTransceiver(pc: PeerConnection) {
    val init = RtpTransceiver.RtpTransceiverInit(
        RtpTransceiver.RtpTransceiverDirection.RECV_ONLY
    )
    val transceiver = pc.addTransceiver(
        MediaStreamTrack.MediaType.MEDIA_TYPE_AUDIO,
        init
    ) ?: error("Failed to add receive-only audio transceiver")
    transceiver.receiver.track()?.setEnabled(true)
}

private fun requireAudioMediaSection(sdp: String) {
    if (sdp.contains("\r\nm=audio ") || sdp.startsWith("m=audio ")) return
    error("Realtime offer missing audio media section")
}
```

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

Gate transcript deltas and final transcripts by item ID when the backend may replace speech:

```kotlin
private fun shouldAcceptItem(itemId: String): Boolean {
    synchronized(transcriptLock) {
        if (ignoredTranscriptItemIds.contains(itemId)) return false

        val current = activeTranscriptItemId
        if (current == null) {
            activeTranscriptItemId = itemId
            return true
        }

        return current == itemId
    }
}
```

## Backend-Controlled Speech

Use this pattern when another backend service owns workflow state:

```python
async def speak_line(session: SessionState, text: str) -> None:
    line = text.strip()
    if not line or session.openai_ws is None:
        return

    if session.openai_response_active:
        await send_openai_event(session, {"type": "response.cancel"})
        session.openai_response_active = False

    session.speech_epoch += 1
    session.current_speech_text = line
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
```

Increment `speech_epoch` or another speech item version before replacing speech. Android should treat that value as the transcript freshness key.

## Tool Loop

Keep tools on the backend. The sideband receives the same Realtime events as the client, including completed function calls. Handle completed function calls from `response.done`, send a function output item, then continue the response:

```python
async def handle_response_done(session: SessionState, response: dict[str, Any]) -> None:
    output_items = response.get("output") or []
    fn_call = next(
        (
            item
            for item in output_items
            if item.get("type") == "function_call"
            and item.get("status") == "completed"
        ),
        None,
    )
    if fn_call is None:
        return

    args = parse_arguments(fn_call.get("arguments"))
    result = await run_tool(str(fn_call.get("name") or ""), args)
    await send_tool_output(
        session,
        call_id=str(fn_call.get("call_id") or ""),
        output=json.dumps(result),
        continue_response=True,
    )
```

Function output item:

```python
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
await send_openai_event(session, {"type": "response.create"})
```

`item.output` must be a string. Use a JSON string for structured results and a JSON error object for tool failures.

## Image Injection

For backend vision augmentation, use this turn barrier:

1. `input_audio_buffer.committed` gives an `item_id` for the completed user audio turn.
2. `conversation.item.added` confirms the user audio item is in the conversation.
3. The backend inserts an image item with `previous_item_id` set to that user audio item ID.
4. The backend sends exactly one `response.create`.

Track pending turns so image injection happens once per completed audio item:

```python
pending_turns: set[str] = set()
sent_images: set[str] = set()

if event_type == "input_audio_buffer.committed":
    item_id = event.get("item_id")
    if isinstance(item_id, str) and item_id:
        pending_turns.add(item_id)

if event_type == "conversation.item.added":
    item = event.get("item") or {}
    item_id = item.get("id")
    if item_id in pending_turns and item_id not in sent_images:
        if not is_user_audio_item(item):
            pending_turns.discard(item_id)
            continue
        pending_turns.discard(item_id)
        sent_images.add(item_id)
        await send_latest_frame_or_continue(openai_sideband, item_id)
```

Insert the latest frame after the user audio turn and before `response.create`:

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

Use a PNG or JPEG data URI for `image_url`. If no frame is available within a short timeout, skip the image item and send `response.create` anyway.
