# Overshoot v0.2 to v1beta Migration Guide

Use this guide when moving an existing Overshoot v0.2 integration to the v1beta stream API. The key change is that Overshoot no longer owns periodic inference for you: your app creates a stream, publishes video into the returned LiveKit room, and explicitly calls chat completions whenever it wants a model result.

## Target Architecture

- Create one Overshoot stream for each active app session or camera feed that needs inference.
- Publish video into the returned LiveKit room with the official LiveKit SDK. Do not create streams with legacy source descriptors such as `source.type=webrtc`.
- Poll the stream status until Overshoot has ingested the first frame before sending the first prompt.
- Run your own prompt scheduler. Each tick calls `/chat/completions` and references the latest frame with `ovs://streams/<stream_id>?frame_index=-1`.
- Keep the stream alive before its lease expires, and apply any refreshed LiveKit publish credentials returned by keepalive to the active publisher or to the reconnect path.
- Delete the Overshoot stream when the app session ends, auto-check is disabled, or the stream is no longer needed.

## Migration Checklist

1. Inventory the current integration points: stream creation, prompt updates, interval settings, result listeners, stream keepalive, stream cleanup, and session state transitions.
2. Add the LiveKit SDK used by your backend language. For Python, install the `livekit` package and publish from a `rtc.VideoSource` or equivalent media source.
3. Replace legacy stream creation payloads with a plain stream create call. Store the returned `id`, `publish.url`, `publish.token`, and lease TTL.
4. Replace server-side interval inference with an app-owned async loop or job. The loop should wait for stream readiness, build a chat completion request, parse the response, then sleep until the next desired prompt interval.
5. Replace prompt patch/update calls with local prompt state. When the workflow step changes, update local state and let the next chat completion use the new prompt.
6. Replace result WebSocket handling with direct chat completion responses. Preserve generation/session guards so stale in-flight completions cannot advance a newer workflow step.
7. Add keepalive on a conservative schedule. For a five-minute lease, a two-minute keepalive is usually fine; using half the returned TTL with a safety cap also works.
8. When keepalive returns a new publish token, save it and make sure reconnects use it. If the SDK exposes a token refresh API, call it; otherwise keep the latest token in session state and rebuild the publisher with that token after a hard LiveKit disconnect.
9. Keep one long-lived HTTP client per backend process or session manager. Reusing the client preserves warm TLS/TCP connections, and optional HTTP/2 can reduce request overhead when both client and server support it.
10. Remove old interval, WebSocket result, prompt patch, and direct WebRTC source configuration from code, environment files, and docs.
11. Keep model selection as ordinary app configuration. You do not need runtime model availability checks if your deployment process already validates the chosen model.
12. Add cleanup on every session end path: normal completion, reset, disconnect, auto-check toggle, backend shutdown, and failure handling.

## Chat Completion Shape

For single-frame checks, reference the latest ingested stream frame as an image input:

```json
{
  "model": "your-confirmed-model",
  "max_tokens": 8,
  "messages": [
    {
      "role": "system",
      "content": "You verify task completion from a live camera view. Return exactly true or false."
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Prompt for the current step. Return exactly true or false."
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "ovs://streams/<stream_id>?frame_index=-1"
          }
        }
      ]
    }
  ]
}
```

Use video inputs when the model needs recent motion instead of a single latest frame. Keep those windows short and explicit, such as the last few seconds, so latency and cost stay predictable.

## Publisher Quality

Publish the best backend-arrived video you can afford to process. Preserve the source resolution when Overshoot needs visual detail, set a bitrate high enough for that resolution, cap frame rate to the inference need, and disable simulcast unless you intentionally want multiple encodings. In LiveKit, prefer a degradation setting that maintains resolution over frame rate when detail matters more than motion smoothness.

Overshoot may still preprocess frames internally, so quality controls are about avoiding avoidable quality loss before ingestion. Verify with debug recordings or preview images taken immediately before publishing to Overshoot.

## Reliability Rules

- Retry stream creation on temporary service errors.
- Retry chat completions on network errors, rate limits, and temporary server errors, with short backoff.
- Do not retry authorization, billing, missing stream, or invalid-request failures as if they were transient.
- Wait for first frame ingestion before the first prompt. Prompting too early can produce empty-segment or no-frame failures.
- Guard every async task with a session generation or equivalent token. Old completions, keepalives, and publisher errors must not mutate a newer session.
- Treat LiveKit disconnect as recoverable when the Overshoot stream and app session are still current. Reconnect with the latest saved publish URL/token and republish the track.
- Treat failed keepalive as terminal for the current Overshoot stream. Stop prompting, clean up local publisher resources, and surface a recoverable app error or restart the stream.

## Python Skeleton

```python
http = httpx.AsyncClient(
    base_url=OVERSHOOT_API_BASE,
    headers={"Authorization": f"Bearer {OVERSHOOT_API_KEY}"},
)

stream = (await http.post("/streams")).json()
stream_id = stream["id"]
publish_url = stream["publish"]["url"]
publish_token = stream["publish"]["token"]

room = rtc.Room()
await room.connect(
    publish_url,
    publish_token,
    options=rtc.RoomOptions(auto_subscribe=False, dynacast=False),
)

source = rtc.VideoSource(width, height)
track = rtc.LocalVideoTrack.create_video_track("app-video", source)
await room.local_participant.publish_track(track, publish_options)

await wait_until_first_frame(http, stream_id)

while session_is_current:
    completion = await http.post(
        "/chat/completions",
        json=build_completion_payload(stream_id, current_prompt),
    )
    handle_model_result(completion.json())
    await asyncio.sleep(prompt_interval_seconds)
```

## Verification Checklist

- A stream is created only when inference is enabled and a first local camera frame exists.
- LiveKit publishing starts with the expected resolution, frame rate, bitrate, codec, simulcast setting, and degradation preference.
- The prompt loop waits for first frame ingestion before the first chat completion.
- Step changes update the prompt used by the next completion without rebuilding the stream unless your app intentionally does so.
- Keepalive runs before lease expiry, stores refreshed publish credentials, and reconnects with the refreshed token after a LiveKit disconnect.
- Stream cleanup runs on completion, reset, auto-check disable, client disconnect, and backend shutdown.
- Existing state-machine tests cover stale result rejection, manual navigation during in-flight prompts, and Overshoot failure handling.
- A live smoke test confirms that completions arrive at the intended cadence and that debug recordings/previews match the video quality you expect Overshoot to see.
