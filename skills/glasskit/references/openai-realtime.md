# OpenAI Realtime

Use this when connecting Rokid audio/video or backend-authored speech to OpenAI Realtime.

## Preferred Shape

Keep `OPENAI_API_KEY` on the backend. Android sends a WebRTC offer to your backend, the backend creates the Realtime call, and Android receives the SDP answer from your backend.

Use `gpt-realtime-1.5` for new Realtime integrations in this skill.

## Backend SDP Broker

Python/FastAPI endpoint shape:

```python
@app.post("/session/{session_id}/realtime")
async def create_realtime_session(session_id: str, request: Request) -> Response:
    offer_sdp = (await request.body()).decode()
    answer_sdp = await session_manager.create_realtime_session(session_id, offer_sdp)
    return Response(content=answer_sdp, media_type="application/sdp")
```

Realtime call creation:

```python
session_config = {
    "type": "realtime",
    "model": "gpt-realtime-1.5",
    "audio": {"output": {"voice": "cedar"}},
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

Open the sideband after extracting `call_id`:

```python
sideband_url = f"wss://api.openai.com/v1/realtime?call_id={call_id}"
async with websockets.connect(
    sideband_url,
    extra_headers={"Authorization": f"Bearer {openai_api_key}"},
) as openai_ws:
    ...
```

## Android Client Patterns

Use the `oai-events` data channel for Realtime event JSON:

```kotlin
val init = DataChannel.Init()
val eventsChannel = peerConnection.createDataChannel("oai-events", init)
```

For direct assistant mode, Android streams microphone audio and optionally camera video to the Realtime peer connection, then renders transcript events from the data channel.

For backend-controlled speech mode, Android should receive audio only. The backend sends user-text events and `response.create`; Android renders the latest transcript and does not decide what the assistant should say.

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
```

Increment `speech_epoch` before replacing speech. Android should clear stale transcript text when it receives a new epoch.

## Tool Loop

When tools are enabled, handle completed function calls from `response.done`, then send a function output item:

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

Deduplicate incoming Realtime events by event id where possible. Treat the sideband as the backend's authoritative control plane.
