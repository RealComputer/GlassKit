# Overshoot Vision

Use this when streaming Rokid camera video to Overshoot and relaying live structured vision results into a HUD or backend workflow.

## Backend Broker

Android should send a WebRTC offer to your backend. The backend creates an Overshoot stream and returns the answer SDP.

Typical create-stream payload:

```python
payload = {
    "source": {
        "type": "webrtc",
        "sdp": offer_sdp,
    },
    "mode": "clip",
    "processing": {
        "target_fps": 6,
        "clip_length_seconds": 0.5,
        "delay_seconds": 0.5,
    },
    "prompt": active_prompt,
    "model": "Qwen/Qwen3.5-27B",
    "output_schema": output_schema,
}
response = await overshoot_http.post("/streams", json=payload)
response.raise_for_status()
```

Return `{ "session_id": "...", "answer_sdp": "..." }` or an equivalent contract to Android.

## Android WebRTC

Use the Overshoot TURN servers listed in `rokid-media-webrtc.md`. Capture 1024x768 at 15 fps unless the product has stricter latency or battery requirements.

The Android app should close the backend session when the app stops or the user exits:

```kotlin
override fun onStop() {
    sessionClient.stop()
    super.onStop()
}
```

## Result WebSocket

The backend listens to the Overshoot stream WebSocket and relays results to Android or to the workflow state machine:

```python
ws_base = overshoot_api_url.replace("http://", "ws://").replace("https://", "wss://")
ws_url = f"{ws_base}/ws/streams/{stream_id}"

async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
    await ws.send(json.dumps({"api_key": overshoot_api_key}))
    async for raw in ws:
        payload = json.loads(raw)
        await session.queue.put({"type": "overshoot.result", **payload})
```

Keep a stream lease alive if the service returns a TTL:

```python
await overshoot_http.post(f"/streams/{stream_id}/keepalive")
```

Close streams on disconnect, app stop, or workflow teardown. Avoid orphaned live streams.

## Prompt Switching

For workflows with multiple active detectors, patch the stream prompt instead of recreating media when possible:

```python
await overshoot_http.patch(
    f"/streams/{stream_id}/config/prompt",
    json={"prompt": next_prompt, "output_schema": next_schema},
)
```

Track a local generation number when switching prompts. Drop late results whose generation or prompt id does not match the active detector.

## Structured Results

Prefer small JSON schemas with stable field names. Good detector fields are domain-specific labels plus generic status fields such as:

- `state`
- `flag`
- `level`
- `count`
- `confidence`

Do not make Android interpret raw detector prose. Normalize backend results before publishing HUD state.
