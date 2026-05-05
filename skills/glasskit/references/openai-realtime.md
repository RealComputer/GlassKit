# OpenAI Realtime

OpenAI Realtime is a low-latency, stateful API for speech-to-speech and
multimodal sessions. A Realtime session is not a normal request/response LLM
call. It is a live connection where:

- media moves over a WebRTC peer connection;
- session state lives in a Realtime `Session`;
- user inputs and model outputs are stored as conversation items;
- voice activity detection normally turns completed user speech into model
  output automatically;
- `response.create` is reserved for explicit backend-controlled turns, such as
  tool output, injected images, or workflow-authored speech;
- tools, transcripts, lifecycle events, and control messages move as JSON
  events.

For Rokid Glasses, use WebRTC for Android media because it gives the most
consistent client-side audio path. Keep `OPENAI_API_KEY` on the backend.
Android sends an SDP offer to the backend, the backend creates the Realtime
call, and Android receives the SDP answer from the backend.

Use `gpt-realtime-1.5` for new Realtime integrations in this skill. It is the
current recommended Realtime voice model for audio-in/audio-out GlassKit apps.

Related reference: [rokid-webrtc.md](rokid-webrtc.md) covers the Android WebRTC
setup, receive-only audio transceivers, SDP normalization, ICE, and lifecycle
cleanup that this document assumes.

## How It Works

Think in two planes:

- **Media plane**: Android's WebRTC peer connection carries microphone audio,
  optional camera media, and remote assistant audio. Do not manually stream
  audio event payloads in this GlassKit path; the WebRTC tracks carry the media.
- **Control plane**: JSON events move over the `oai-events` WebRTC data channel
  and, when needed, a backend sideband control channel attached to the same
  Realtime call.

The important objects are:

- **Session**: model, voice, instructions, audio config, tools, turn detection,
  and output modalities. Most fields can be updated during a session. Do not
  assume `voice` can be changed after the model has produced audio.
- **Conversation item**: a user message, assistant message, tool call, tool
  output, image input, or audio item in the live conversation.
- **Response**: one model turn. In the default voice path, Realtime creates the
  response automatically after VAD decides the user has stopped speaking. Send
  `response.create` only when the app has deliberately disabled automatic
  responses or when the backend adds an item that needs a model answer.
- **Sideband**: a server control channel attached with `call_id`. Use it when
  backend business logic, tools, workflow state, or guardrails must stay
  server-side.

### Response Creation

The default GlassKit voice pattern is automatic response creation. Leave VAD
enabled, let Realtime decide when the user has finished speaking, and do not
send `response.create` for each microphone turn.

Use explicit `response.create` only for backend-gated turns. In that mode, keep
VAD enabled for turn detection but set `create_response` to `False`, wait for
the completed user turn or backend workflow event, add any required
conversation items, and then send exactly one `response.create`.

## GlassKit Patterns

### Direct Assistant

Use this when the model can own the conversation. Android streams microphone
audio and, if the app has validated direct camera behavior for its model and
account, camera media to the Realtime peer connection. Android receives remote
assistant audio and renders transcript events from `oai-events`.

This is the simplest shape for a conversational assistant. The backend still
brokers SDP and handles tools so secrets and private data stay off the glasses.
Keep automatic turn creation enabled for this pattern. Android streams user
audio, Realtime detects the end of the user's turn, and the assistant response
starts without Android or the backend sending `response.create`.

### Backend-Augmented Vision

Use this when you need more reliable spatial understanding, object detection,
or domain-specific vision. Android runs two links:

- audio to OpenAI Realtime, brokered by the backend;
- camera video to a backend vision service, such as RF-DETR, Overshoot, or an
  `aiortc` receiver.

The backend stores the latest useful frame or structured vision result. After a
user audio turn, it can insert an `input_image` conversation item and then send
`response.create`. This avoids making the glasses interpret raw vision results
and keeps product logic backend-owned.

This is an exception to the default automatic response flow. Keep VAD, but
disable automatic response creation so the backend has time to inject the image
or structured vision result before the model answers:

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

### Backend-Controlled Speech

Use this for server-authoritative workflows where the backend decides each step,
HUD state, and exact spoken line. Android should receive audio only. Configure
the Realtime session so user audio does not automatically create assistant
turns, then let the backend send text conversation items such as `Speak exactly
this line: ...` followed by `response.create`. Android renders only the latest
transcript and clears stale partial text when `speech_epoch` changes.

This is the best fit for guided work on glasses: Android stays thin, the backend
owns state, and Realtime provides low-latency speech plus transcript events.

## Backend SDP Broker

The backend can be Python, Node, or any language that can accept SDP and send a
multipart request. For server-authoritative patterns it also attaches a
sideband control channel to the Realtime call. Use Python/FastAPI snippets
below as the compact reference shape; do not treat Python as required.

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

Realtime call creation for backend-controlled speech or vision injection:

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

answer_sdp = upstream.text.strip()
call_id = upstream.headers["location"].rstrip("/").split("/")[-1]
```

Validate both outputs before returning to Android:

```python
if not call_id or not answer_sdp.startswith("v="):
    raise HTTPException(
        status_code=502,
        detail="OpenAI realtime response missing call_id or valid answer SDP",
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

The sideband is the backend's authoritative control channel, not the glasses
media transport. It can monitor session events, send `session.update`, call
tools, insert conversation items, cancel active speech, and create responses.

## Android Client Contract

Use the `oai-events` data channel for Realtime event JSON:

```kotlin
val eventsChannel = peerConnection.createDataChannel(
    "oai-events",
    DataChannel.Init()
)
```

Create data channels, local tracks, and receive-only transceivers before
creating the offer. Wait for ICE gathering, POST the full local SDP to the
backend, normalize the answer SDP, then set the remote description.

For direct assistant mode:

- add a local microphone audio track;
- add a camera track only for the direct-vision path you have validated;
- set `OfferToReceiveAudio` to `"true"` so assistant speech plays on Rokid;
- parse `conversation.item.input_audio_transcription.completed` for user text;
- parse `response.output_audio_transcript.delta` and `.done` for assistant HUD
  text.

For backend-controlled speech:

- do not add a local microphone track unless the app needs user audio in this
  Realtime session;
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
    await publish_hud_state(session)
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

Increment `speech_epoch` before replacing speech. Android should treat that
epoch as the transcript freshness key.

Pair the speech contract with instructions that make exact playback explicit:

```text
When the user's message starts with `Speak exactly this line:`, speak that line
exactly. Do not paraphrase, summarize, add commentary, or call tools in that
case.
```

## Tool Loop

Keep tools on the backend. The sideband receives the same Realtime events as the
client, including completed function calls. Handle tool calls from
`response.done`, send a function output item, then continue the response:

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

For tool errors, return a JSON error object as the function output instead of
dropping the call. The model can then recover or explain the failure.

## Image Injection

For backend vision augmentation, insert the latest frame after a user audio turn
and before `response.create`:

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

Send the latest useful frame, not a backlog. If no frame is available quickly,
either create the response without vision or ask the user to show the scene
again. Avoid letting old frames answer current-world questions.

## Lifecycle Notes

- A Realtime call is session state. Tear it down when the Rokid app stops or the
  backend control session closes.
- Stop or replace active speech with `response.cancel` before sending a newer
  backend-authored line.
- Use generation numbers for vision and Realtime runtimes. Drop late events from
  stale generations.
- Surface connection state to the HUD, but keep workflow decisions on the
  backend for multi-step guidance apps.
- Prefer one Realtime session per active user workflow. Start fresh after app
  background/foreground or backend reconnect unless the product explicitly needs
  resume semantics.
- Do not expose standard OpenAI API keys to Android. If a direct-client design is
  required, mint a short-lived client secret on the backend instead.

## Official Docs

- Realtime overview: https://developers.openai.com/api/docs/guides/realtime
- WebRTC connection: https://developers.openai.com/api/docs/guides/realtime-webrtc
- Managing conversations: https://developers.openai.com/api/docs/guides/realtime-conversations
- Server-side controls: https://developers.openai.com/api/docs/guides/realtime-server-controls
- `gpt-realtime-1.5`: https://developers.openai.com/api/docs/models/gpt-realtime-1.5
