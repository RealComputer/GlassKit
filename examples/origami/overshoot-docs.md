# Authentication
Source: https://docs.overshoot.ai/api-reference/authentication

Bearer API keys for every public HTTP request, except the open model and pricing endpoints.

Every public HTTP request requires a bearer API key, except [list models](/api-reference/list-models) and the public pricing endpoints.

```http theme={null}
Authorization: Bearer <api_key>
```

* `401` — the key is missing, unknown, or revoked.
* `403` — the key is valid but cannot access the requested resource.
* The publish token returned by [`POST /streams`](/api-reference/create-stream) is only for publishing media. It does **not** replace the API key for HTTP calls.

Keys are prefixed with `ovs-` and managed in the [Overshoot dashboard](https://platform.overshoot.ai).

<Note>
  Calls using your API key incur cost. Treat keys as secrets — never commit them or expose them in client-side code.
</Note>


# Chat completions
Source: https://docs.overshoot.ai/api-reference/chat-completions

POST /chat/completions
OpenAI-compatible chat completions.

Text-only requests are allowed. To reference live stream media, put
`ovs://streams/<id>?...` inside an `image_url` or `video_url` content part. Unknown
fields are accepted for SDK compatibility.

Set `stream: true` to receive `text/event-stream`. When
`stream_options.include_usage` is also `true`, the stream may include a final
usage chunk.


## Referencing a stream

The `messages[].content[]` array accepts standard OpenAI content parts plus two Overshoot-specific URL shapes:

* **`image_url`** — points at a single frame of a stream.
* **`video_url`** — points at a window of frames.

Both wrap an `ovs://` reference of the form:

```
ovs://streams/{stream_id}?<query>
```

The `ovs://` scheme is a reference identifier — the server parses it to pull out `stream_id` and the query, then resolves frames internally. It is not a fetchable URL. The `<query>` is what selects the moment you want. Different keys for single frames vs. windows.

### Image URL — query params

For `type: "image_url"`. **Exactly one** anchor is required.

| Param          | Type     | Required        | Description                                                                                                                                                 |
| -------------- | -------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frame_index`  | int      | Anchor (one of) | Lifetime-indexed frame number. Negative = relative to live edge; `-1` is the most recent frame.                                                             |
| `timestamp_ms` | int      | Anchor (one of) | Absolute stream-clock ms since `first_frame_at_ms`.                                                                                                         |
| `offset_ms`    | int      | Anchor (one of) | Offset relative to "now" (live edge at request time). Negative = past.                                                                                      |
| `tolerance_ms` | int (>0) | Optional        | How far the resolver may snap to find a frame. **Default `100`. Ignored when `frame_index` is set.**                                                        |
| `direction`    | enum     | Optional        | `nearest` \| `forward` \| `backward`. Resolution preference when no exact match within tolerance. **Default `nearest`. Ignored when `frame_index` is set.** |

```json theme={null}
{ "type": "image_url",
  "image_url": { "url": "ovs://streams/{id}?frame_index=-1" }
}
```

### Video URL — query params

For `type: "video_url"`. Requires **one start anchor**, accepts **one optional end anchor** (defaults to the live edge), plus an optional `max_fps`.

| Param                | Type       | Required              | Description                                                                                                   |
| -------------------- | ---------- | --------------------- | ------------------------------------------------------------------------------------------------------------- |
| `start_frame_index`  | int        | Start anchor (one of) | Lifetime index where the segment begins.                                                                      |
| `start_timestamp_ms` | int        | Start anchor (one of) | Absolute stream-clock ms where the segment begins.                                                            |
| `start_offset_ms`    | int        | Start anchor (one of) | Offset from now where the segment begins. Negative = past (e.g. `-5000` is "5s ago").                         |
| `end_frame_index`    | int        | End anchor (optional) | Lifetime index where the segment ends.                                                                        |
| `end_timestamp_ms`   | int        | End anchor (optional) | Absolute stream-clock ms where the segment ends.                                                              |
| `end_offset_ms`      | int        | End anchor (optional) | Offset from now where the segment ends.                                                                       |
| `max_fps`            | float (>0) | Optional              | Cap on frames per second sampled from the segment. **Default `1.0`.** Halving `max_fps` halves visual tokens. |

Start and end anchor types may differ — `start_offset_ms=-30000&end_frame_index=523` is valid.

```json theme={null}
{ "type": "video_url",
  "video_url": { "url": "ovs://streams/{id}?start_offset_ms=-5000&max_fps=2" }
}
```

### Resolution rules

* **Negative `frame_index` / `offset_ms`** are evaluated against `last_frame_index` / now at request time. The same URL can resolve to different frames on consecutive calls.
* **Old frames clamp.** A `frame_index` (or `start_frame_index`) older than `first_available_frame_index` clamps up to the oldest available frame. Request **succeeds**, possibly on a different frame than asked.
* **Future frames fail.** A `frame_index` newer than `last_frame_index` returns `422`. There is no "wait until that frame arrives".
* **Duplicate query keys** (`?frame_index=1&frame_index=2`) → `422`.
* **Setting more than one anchor** of the same kind (e.g. two `start_*`, or `frame_index` + `timestamp_ms`) → `422`.

### Example — single-frame question

```json theme={null}
{
  "model": "Qwen/Qwen3.6-27B-FP8",
  "messages": [{
    "role": "user",
    "content": [
      { "type": "text", "text": "What is the person doing right now?" },
      { "type": "image_url",
        "image_url": { "url": "ovs://streams/{id}?frame_index=-1" }
      }
    ]
  }]
}
```

### Example — last-N-seconds question

```json theme={null}
{
  "model": "google/gemma-4-26B-A4B-it",
  "messages": [{
    "role": "user",
    "content": [
      { "type": "text", "text": "Did anything happen in the last 5 seconds?" },
      { "type": "video_url",
        "video_url": { "url": "ovs://streams/{id}?start_offset_ms=-5000" }
      }
    ]
  }]
}
```

For more usage patterns, see the [Chat Completion guide](/chat-completion).


# Core flow
Source: https://docs.overshoot.ai/api-reference/core-flow

The end-to-end lifecycle: create a stream, publish frames, query frames with chat completions.

```text theme={null}
client -> POST /streams -> Overshoot
client <- {id, publish:{url,token}} <- Overshoot

client -> publish media using publish.url + publish.token

client -> POST /chat/completions -> Overshoot
         messages include image_url/video_url references to ovs://streams/<id>?...
```

## Lifecycle

1. [`POST /streams`](/api-reference/create-stream) creates a stream and returns a publish token.
2. The client publishes video using `publish.url` and `publish.token` (see [LiveKit client flow](/api-reference/livekit-client-flow)).
3. Overshoot makes recent frames available for inference.
4. The client calls [`POST /chat/completions`](/api-reference/chat-completions) with text and optional `ovs://` media references.
5. The client calls [`POST /streams/{id}/keepalive`](/api-reference/keepalive-stream) before the 5-minute lease expires.
6. [`DELETE /streams/{id}`](/api-reference/delete-stream) ends the stream.

There is no public `POST /streams/{id}/infer` contract.


# Create checkout session
Source: https://docs.overshoot.ai/api-reference/create-checkout

POST /billing/checkout
Create a checkout session for buying prepaid credits. `amount_cents` must be at
least `100`.




# Create stream
Source: https://docs.overshoot.ai/api-reference/create-stream

POST /streams
Create a new video inference stream. Returns connection details for the chosen transport.

**Workflow:** Create stream → connect video source → receive results on WebSocket → send keepalives → close when done.

**Transport options:**
- **Native** (default, recommended): Omit `source`. Response includes `livekit.url` and `livekit.token` for publishing video.
- **WebRTC**: Set `source.type: 'webrtc'` with an SDP offer. Response includes `webrtc` answer and `turn_servers`.
- **LiveKit**: Set `source.type: 'livekit'` with your room URL and token.

**Processing modes:**
- **Clip mode**: Send `target_fps`, `clip_length_seconds`, `delay_seconds` for temporal analysis (motion, actions).
- **Frame mode**: Send `interval_seconds` for static analysis (OCR, object detection).

**Limits:** 5 concurrent streams per API key. Requires credits.

## What you get

The response carries:

* **`id`** — pass this in every later URL: `/v1beta/streams/{id}/...` plus stream URLs you embed in chat completion messages.
* **`publish.url`** + **`publish.token`** — feed these to a [LiveKit client SDK](https://docs.livekit.io/reference/) to connect a video source. Any LiveKit publisher works (browser, native, server-to-server). The token is short-lived; use the one returned by `/keepalive` if your publisher reconnects later.
* **`expires_at_ms`** + **`ttl_seconds`** — the lease deadline. Call `/keepalive` before it elapses (every \~2 minutes is safe). After expiry the stream's `state` flips to `ended` and stays there.

The stream sits in `active` state immediately, even before the first frame arrives. `GET /streams/{id}` returns `last_frame_at_ms: null` until a publisher actually delivers a frame.


# Delete stream
Source: https://docs.overshoot.ai/api-reference/delete-stream

DELETE /streams/{stream_id}
End a stream and release its resources. Idempotent on already-deleted streams within the lookup window.

Tears down a [Stream](/the-stream), drops its retained frames, and releases
its LiveKit room. Call this as soon as you're done with a session — don't
rely on the lease timeout if you can help it. After deletion, the
`stream_id` can no longer be referenced from
[`/chat/completions`](/api-reference/chat-completions).


# Error shapes
Source: https://docs.overshoot.ai/api-reference/errors

Status codes, error codes, and the JSON envelopes used across stream and chat endpoints.

Stream lifecycle endpoints use standard JSON error bodies:

```json theme={null}
{ "detail": "Stream not found" }
```

Chat-completions errors are wrapped as:

```json theme={null}
{
  "detail": {
    "error": {
      "message": "Stream not found: <stream_id>",
      "type": "stream_error",
      "code": "stream_not_found"
    }
  }
}
```

Validation failures from chat-completions use:

```json theme={null}
{
  "error": "validation_error",
  "message": "Request validation failed",
  "details": []
}
```

## Status codes

| Status | Meaning                                                                                                         |
| -----: | --------------------------------------------------------------------------------------------------------------- |
|  `400` | Invalid stream URL/query, invalid segment, unsupported model/media combination, or provider safety block.       |
|  `401` | Missing or invalid bearer API key.                                                                              |
|  `402` | Billing denied inference.                                                                                       |
|  `403` | Valid key, but the requested resource belongs to another user.                                                  |
|  `404` | Stream missing, stream deleted, lease expired, no retained frames matched, or pricing/model resource not found. |
|  `409` | Wrong region, multiple stream regions, or requested lifetime frame index has not arrived yet.                   |
|  `410` | Requested exact lifetime frame index has been evicted.                                                          |
|  `422` | Request validation failed.                                                                                      |
|  `429` | Per-user inference rate limit exceeded, or the model provider rate-limited the request.                         |
|  `500` | Internal processing error.                                                                                      |
|  `502` | Model provider request failed, unauthorized, or returned a server error.                                        |
|  `503` | Service temporarily unavailable.                                                                                |
|  `504` | Model provider request timed out.                                                                               |

## Chat completions error codes

| Code                      | Meaning                                                                  |
| ------------------------- | ------------------------------------------------------------------------ |
| `stream_url_invalid`      | URL used the `ovs://` scheme but did not match `ovs://streams/<id>?...`. |
| `query_param_invalid`     | Missing, duplicate, unknown, or malformed media query parameter.         |
| `stream_not_found`        | Stream is missing or unavailable.                                        |
| `stream_unauthorized`     | API key user does not own the referenced stream.                         |
| `segment_empty`           | No retained frames matched the requested media URL.                      |
| `segment_invalid`         | Resolved video end is at or before the resolved start.                   |
| `frame_evicted`           | Requested lifetime frame index has been evicted.                         |
| `frame_not_yet_produced`  | Requested lifetime frame index has not arrived yet.                      |
| `model_unavailable`       | The requested model is not currently available.                          |
| `model_video_unsupported` | Requested a video segment for an image-only model/provider.              |
| `provider_safety_block`   | Provider accepted the request but blocked the content.                   |
| `billing_denied`          | Billing state denied the inference request.                              |
| `upstream_http_<status>`  | The model provider returned a non-200 HTTP status.                       |
| `upstream_timeout`        | The model provider timed out.                                            |
| `upstream_request_failed` | The model provider request failed before a response was received.        |

## Upstream provider errors

Model provider errors preserve the provider status and a bounded response body when available:

```json theme={null}
{
  "detail": {
    "error": {
      "message": "Upstream model error",
      "type": "upstream_error",
      "code": "upstream_http_400",
      "upstream": {
        "provider": "google",
        "status": 400,
        "body": { "error": { "message": "..." } },
        "rate_limits": null
      }
    }
  }
}
```

## Rate limit headers

Per-user inference rate limiting is configurable. Successful and `429` responses include:

| Header                  | Meaning                                           |
| ----------------------- | ------------------------------------------------- |
| `x-ratelimit-limit`     | Current per-user request-per-second limit.        |
| `x-ratelimit-remaining` | Remaining requests in the current second.         |
| `x-ratelimit-reset`     | Epoch time when the current second window resets. |
| `retry-after`           | Present on 429; currently `1`.                    |


# Get prepaid balance
Source: https://docs.overshoot.ai/api-reference/get-balance

GET /billing/accounts/me/balance
Return the authenticated user's prepaid balance. `balance_cents` is for display;
`balance_microcents` is the exact billing unit. Inference can return `402` when
billing denies a request.




# Get model pricing
Source: https://docs.overshoot.ai/api-reference/get-pricing

GET /billing/pricing/{model}
Return pricing for one model. The `model` path may contain slashes.



# Get stream
Source: https://docs.overshoot.ai/api-reference/get-stream

GET /streams/{stream_id}

## Reading the response

The response covers three axes you'll mix when authoring stream URLs:

* **Wall-clock time** — `created_at_ms`, `first_frame_at_ms`, `last_frame_at_ms`, `expires_at_ms`. Unix ms. Useful for absolute deadlines and `timestamp_ms` math (the `timestamp_ms` anchor is measured from `first_frame_at_ms`).
* **Stream-clock time** — `stream_time_ms`. Monotonically increases from `0` at the first frame; resets to no other clock if the publisher pauses.
* **Frame indices** — `last_frame_index`, `first_available_frame_index`. Lifetime indices that never reset, even after eviction. The pair defines the retention window — anything in `[first_available_frame_index, last_frame_index]` resolves cleanly; older indices clamp up to `first_available_frame_index`.

Until the publisher delivers a first frame, every `*_at_ms` / `*_index` field returns `null` (only `id`, `state`, `created_at_ms`, `expires_at_ms`, `ttl_seconds` are populated). Polling `last_frame_at_ms` is the cheapest "wait for ingest" check.

After the stream ends, `state` becomes `ended` with `ended_at_ms` and `end_reason` set. The endpoint keeps returning the ended record for a short tombstone window, then `404`s.


# Introduction
Source: https://docs.overshoot.ai/api-reference/introduction

Use the Overshoot REST API to ingest live video, query vision-language models, and manage stream lifecycle.

The Overshoot REST API turns a live video feed into a conversation. Publish frames over WebRTC, then call an OpenAI-compatible chat completions endpoint to ask any vision-language model about your stream — over the last few seconds, the latest frame, or anywhere in the stream's history.

## Endpoints

* [List models](/api-reference/list-models) — discover the vision-language models you can target in chat completions.
* [Create stream](/api-reference/create-stream) — open a live stream and get a LiveKit room URL + token to start publishing frames.
* [Get stream](/api-reference/get-stream) — inspect the state of a stream: frame counts, recent FPS, lease expiry.
* [Renew stream lease](/api-reference/keepalive-stream) — keep a stream alive past the default 5-minute idle window.
* [Delete stream](/api-reference/delete-stream) — end a stream and release its resources.
* [Chat completions](/api-reference/chat-completions) — ask any vision-language model about a stream's frames.

## Base URL

```text theme={null}
https://api.overshoot.ai/v1beta
```

Billing endpoints are mounted on the same host under `/billing`.

## Authentication

Bearer tokens. Include your API key on every authenticated request:

```bash theme={null}
curl https://api.overshoot.ai/v1beta/streams/<id> \
  -H "Authorization: Bearer ovs-..."
```

Keys are prefixed with `ovs-` and managed in the [Overshoot dashboard](https://platform.overshoot.ai). [List models](/api-reference/list-models) is the only unauthenticated endpoint.

<Note>
  Calls using your API key incur cost. Treat keys as secrets — never commit them or expose them in client-side code.
</Note>

## Errors

Non-2xx responses use this shape:

```json theme={null}
{ "detail": "Stream not found" }
```

| Code         | Meaning                                                          |
| ------------ | ---------------------------------------------------------------- |
| `401`, `403` | Missing or invalid API key.                                      |
| `402`        | Insufficient credits.                                            |
| `404`        | Stream not found, or not owned by your key.                      |
| `422`        | Request validation failed. `details` lists the offending fields. |
| `503`        | Service is draining or starting up — retry.                      |

## Related

* [The Stream](/the-stream) — concept guide for the stream lifecycle.
* [Models](/models) — overview of available vision-language models.
* [Chat Completion](/chat-completion) — the URL grammar for referencing frames and segments.
* [Best practices](/best-practices) — production tips for low latency and cost.


# Renew stream lease
Source: https://docs.overshoot.ai/api-reference/keepalive-stream

POST /streams/{stream_id}/keepalive
Renew the stream lease and pay for elapsed streaming time. **Call every 10-20 seconds.** Streams expire after ~45 seconds without a keepalive.

Each call charges for time since the last keepalive. If credits are insufficient (402), the lease is NOT renewed and the stream will expire.

For native transport, the response includes a refreshed `livekit_token`.

## When to call

Streams expire 5 minutes after the last keepalive (or creation, if no keepalive has happened yet). Call `/keepalive` every \~2 minutes — clock skew is real and the cost of a missed renewal is the whole stream.

A keepalive on a stream that's already `ended` returns `404`. Streams cannot be revived; create a new one.

## What you get back

Every successful keepalive returns:

* A new **`expires_at_ms`** set to `now + ttl_seconds`.
* A **fresh LiveKit `publish.token`**. Save it — if your publisher disconnects from the room, you'll need a current token to rejoin without recreating the stream. Old tokens may stop working.
* The current **`stream_time_ms`** (matches `GET /streams/{id}`).


# Limits and retention
Source: https://docs.overshoot.ai/api-reference/limits

Frame retention window and other API limits.

* Stream media URLs can reference frames within the **retained history window**, currently **600 seconds**.
* Frames may be compressed or resized before inference.
* Lifetime frame indices remain stable as older frames leave the retained window.


# List models
Source: https://docs.overshoot.ai/api-reference/list-models

GET /models
List model IDs and availability in an OpenAI-compatible shape. No auth required.
Use the `id` value as the `model` field in inference requests.


## What's in the response

* Each entry's **`id`** is what you pass as `model` on `/chat/completions`. Use it verbatim — IDs are case-sensitive.
* **`status`** is the only mutable field worth checking:
  * `ready` — at least one healthy replica is serving. Use it.
  * `unavailable` — model is not currently serving. Don't use; retry later or fall back to another model.
* A model that's `ready` here can still return `503` on `/chat/completions` if its replica falls over between calls. Always handle `503` with a retry or a fallback to another `ready` model.

This endpoint is the **only** one that doesn't require an API key. List it before every session — don't hardcode model IDs.


# List pricing
Source: https://docs.overshoot.ai/api-reference/list-pricing

GET /billing/pricing
List public model prices. No auth required. Money fields use **integer microcents**:
`1 cent = 1,000,000 microcents`.




# LiveKit client flow
Source: https://docs.overshoot.ai/api-reference/livekit-client-flow

Browser example showing how to create a stream, publish via LiveKit, and renew the lease.

```js theme={null}
import { Room, createLocalTracks } from "livekit-client";

const API = "https://api.overshoot.ai/v1beta";

async function createStream(apiKey) {
  const res = await fetch(`${API}/streams`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
    },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

const { id, publish } = await createStream(apiKey);

const room = new Room({ adaptiveStream: true, dynacast: true });
await room.connect(publish.url, publish.token);

const [videoTrack] = await createLocalTracks({ video: true, audio: false });
await room.localParticipant.publishTrack(videoTrack);

setInterval(async () => {
  const res = await fetch(`${API}/streams/${id}/keepalive`, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  if (!res.ok) return;
  const ka = await res.json();
  await room.updateToken(ka.publish.token);
}, 240_000);
```

Any LiveKit publisher works (browser, native, server-to-server). See the [LiveKit SDK reference](https://docs.livekit.io/reference/) for non-browser clients.


# Prompt cache and threads
Source: https://docs.overshoot.ai/api-reference/prompt-cache

Reuse cached prompt prefixes across related chat completion requests.

Use the same `thread_id` for related requests in the same user conversation and model to improve prompt-cache reuse when available.

```json theme={null}
{
  "model": "google/gemma-4-26B-A4B-it",
  "thread_id": "session-123",
  "messages": [{ "role": "user", "content": "Continue from our previous context." }]
}
```

Cache observability is returned under `overshoot.cache`:

```json theme={null}
{
  "overshoot": {
    "cache": {
      "thread_id": "session-123",
      "cache_hit": true,
      "cached_input_tokens": 5000
    }
  }
}
```

* `thread_id` is the ID you supplied, or `null` when none was provided.
* `cache_hit` is true when cached prompt tokens were reported.
* `cached_input_tokens` is the number of prompt tokens served from prefix cache.

<Note>
  Cache metadata is observability only. It is not a guarantee that future requests will receive a cache hit.
</Note>


# Region behavior
Source: https://docs.overshoot.ai/api-reference/regions

How regional routing works and how to skip the redirect/retry step.

Streams are regional resources. If your application knows which region owns a stream, you can include a region header to avoid an extra redirect/retry step.

Clients may send:

```http theme={null}
X-Overshoot-Region: us-west1
```

or:

```http theme={null}
X-Overshoot-Region: us-central1
```

If a request reaches the wrong region, the API returns `409` with a `region_error` body that identifies the expected or requested region. Responses expose `X-Overshoot-Region` with the serving region.

<Note>
  One chat-completions request cannot reference streams from multiple regions.
</Note>


# Stream lifecycle
Source: https://docs.overshoot.ai/api-reference/stream-lifecycle

How streams transition between active and ended, and how frame availability is exposed.

Streams are live resources. There is no public pause, resume, or idle state in the current API. A stream is `active` until it ends or expires; frames may be arriving, not arriving yet, or arriving at a weak cadence.

## Frame availability

Frame availability is exposed through [`GET /streams/{id}`](/api-reference/get-stream):

* `first_frame_at_ms` is non-null after the first frame is captured.
* `recent_fps` is computed over the current frame-metrics bucket for active streams.
* `retained_frame_count` counts frames still available for inference.
* `evicted_frame_count` counts frames evicted from the stream history window.
* `last_frame_index` is the 0-indexed lifetime index of the most recent frame.
* `first_available_frame_index` is the 0-indexed lifetime index of the oldest frame still retained.
* `first_available_frame_at_ms` is the epoch ms timestamp of that oldest retained frame.
* `end_reason` is `null` while active. On ended streams it is `"deleted"` for explicit deletes and `"expired"` for system-driven termination.

## Frame indexing

Frame indices used by inference URLs are **stream-lifetime indices**, not retained-window positions. `frame_index=0` means the first frame ever captured for that stream. Exact image lookups fail if that frame has been evicted; video ranges are intersected with the retained window.

When a stream ends, live counters and timestamps are snapshotted. [`GET /streams/{id}`](/api-reference/get-stream) on an ended stream returns those final values.


# Stream media URLs
Source: https://docs.overshoot.ai/api-reference/stream-media-urls

The ovs:// URL grammar for referencing frames and segments inside chat completions.

Overshoot media URLs have this shape:

```text theme={null}
ovs://streams/<stream_id>?<query>
```

These URLs are **reference identifiers** inside chat-completions requests. Overshoot resolves them to the requested stream media before calling the selected model. They are not fetchable HTTP URLs.

Only `ovs://streams/...` URLs use this resolution behavior. Non-Overshoot `image_url` and `video_url` values are sent as provided to the selected model.

<Warning>
  Do not use public HTTP media URLs for inference. Use `ovs://streams/<id>?...` inside the chat-completions request.
</Warning>

## Image URL queries

Use `image_url` when the request should resolve to one frame.

| Param          | Type                                 | Notes                                                                                   |
| -------------- | ------------------------------------ | --------------------------------------------------------------------------------------- |
| `timestamp_ms` | int                                  | Stream-relative timestamp.                                                              |
| `offset_ms`    | int                                  | Negative offset anchors to latest frame; non-negative anchors to oldest retained frame. |
| `frame_index`  | int                                  | Lifetime frame index. Negative values count from latest retained frame; `-1` is latest. |
| `tolerance_ms` | int                                  | Default `100`; only meaningful with `timestamp_ms` or `offset_ms`.                      |
| `direction`    | `nearest` \| `forward` \| `backward` | Default `nearest`; only meaningful with timestamp/offset lookup.                        |

Exactly one of `timestamp_ms`, `offset_ms`, or `frame_index` is required.

```text theme={null}
ovs://streams/<id>?frame_index=-1
ovs://streams/<id>?timestamp_ms=12000&tolerance_ms=250
ovs://streams/<id>?offset_ms=-5000&direction=backward
```

## Video URL queries

Use `video_url` when the request should resolve to multiple frames and be sent to the selected model as a generated clip.

| Param                | Type  | Notes                                                             |
| -------------------- | ----- | ----------------------------------------------------------------- |
| `start_frame_index`  | int   | One `start_*` param is required.                                  |
| `end_frame_index`    | int   | Optional; end is exclusive.                                       |
| `start_timestamp_ms` | int   | One `start_*` param is required.                                  |
| `end_timestamp_ms`   | int   | Optional; end is exclusive.                                       |
| `start_offset_ms`    | int   | One `start_*` param is required.                                  |
| `end_offset_ms`      | int   | Optional; end is exclusive.                                       |
| `max_fps`            | float | Default `1.0`; max frames retained per second after downsampling. |

```text theme={null}
ovs://streams/<id>?start_frame_index=-30&max_fps=2
ovs://streams/<id>?start_timestamp_ms=10000&end_timestamp_ms=15000&max_fps=4
ovs://streams/<id>?start_offset_ms=-10000&end_offset_ms=0
```

Resolution is intersected with the retained frame window. If the requested range has no available frames, the request fails with `segment_empty`.


# Best practices
Source: https://docs.overshoot.ai/best-practices

Patterns for keeping latency low, costs predictable, and streams alive.

A few habits make Overshoot apps feel snappy and behave well in production.

## Latency

<CardGroup>
  <Card title="Send only what you need" icon="image">
    A single frame (`image_url`) costs a fraction of a video segment. Most "what's happening?" questions only need the latest frame.
  </Card>

  <Card title="Keep prompts terse" icon="comment">
    System messages and few-shot examples are tokens too. Visual tokens dominate, but text adds up at high frame counts.
  </Card>

  <Card title="Pick a smaller model" icon="bolt">
    Start with `gemma-4-26B-A4B-it` or `Qwen3.6-35B-A3B-FP8`. Move up only if quality is bad.
  </Card>

  <Card title="Drop resolution" icon="compress">
    480p Qwen costs \~5× fewer tokens per frame than 1080p. Publish at the resolution you actually need.
  </Card>
</CardGroup>

## Streams

* **Renew before you have to.** Streams expire after **5 minutes** idle. Call `/keepalive` every **2 minutes**.
* **Save the keepalive token.** Each `/keepalive` returns a fresh LiveKit token — keep it around for reconnects.
* **Delete when done.** A `DELETE /streams/{id}` releases resources immediately instead of waiting for the lease.

## Reliability

* **Try to list models before you start.** `/models` is the source of truth. Don't hardcode an `id` and assume it's serving.
* **Handle `503` on completions.** It means the replica fell over. Retry with backoff, or fall back to another `ready` model.
* **Treat `frame_index` as monotonic.** If you reference an old index that's been evicted, the resolver clamps to the oldest available — your request still succeeds, but on a different frame than you asked for.

<Visibility>
  ## Production playbook — for agents

  ### Stream lifecycle pseudo-code

  ```python theme={null}
  async def with_stream(prompt_fn):
      stream = await create_stream()
      keepalive_task = asyncio.create_task(keepalive_loop(stream.id))
      try:
          async with publisher(stream.publish.url, stream.publish.token):
              await wait_for_first_frame(stream.id, timeout=10)
              return await prompt_fn(stream.id)
      finally:
          keepalive_task.cancel()
          await delete_stream(stream.id)
  ```

  `keepalive_loop` runs `POST /streams/{id}/keepalive` every 90s and updates the publisher with the fresh token. `wait_for_first_frame` polls `GET /streams/{id}` until `last_frame_at_ms` is non-null — issuing chat completions before this returns produces validation errors.

  ### Retry budget

  | Operation                      | Retry on       | Backoff      | Cap                                      |
  | ------------------------------ | -------------- | ------------ | ---------------------------------------- |
  | `POST /streams`                | `503`          | 1s, 2s, 4s   | 3 attempts                               |
  | `POST /streams/{id}/keepalive` | network, `503` | 1s, 1s, 1s   | 3 attempts before treating as fatal      |
  | `POST /chat/completions`       | `503`, network | 0.5s, 1s, 2s | 3 attempts, then fall back to next model |

  Don't retry `4xx` other than `429` (which Overshoot doesn't currently emit, but is a sensible defensive case).

  ### Visual-token math

  Treat the request size as approximately:

  ```
  prompt_tokens ≈ text_tokens + n_frames × tokens_per_frame
  ```

  For Qwen at 480p, `tokens_per_frame ≈ 200`. For Gemma 4, `tokens_per_frame` is whatever budget you set per-request (default 256). A 60-frame Gemma request at the default budget is \~15K visual tokens before any text; a 1-second window at 30 fps on Qwen is \~6K.

  Latency scales roughly linearly with `prompt_tokens + completion_tokens`. To halve latency, halve one of:

  * frames in the segment,
  * resolution of the publisher,
  * per-frame token budget (Gemma only).

  ### Picking the cheapest viable anchor

  | Use case                           | Anchor                                                     | Why                                              |
  | ---------------------------------- | ---------------------------------------------------------- | ------------------------------------------------ |
  | "What's in front of me right now?" | `image_url` with `frame_index=-1`                          | One frame; minimum tokens.                       |
  | "Did anything happen recently?"    | `video_url` with `start_offset_ms=-3000`                   | Short, anchored to live edge.                    |
  | "Replay 10:00–10:30"               | `video_url` with `start_timestamp_ms` + `end_timestamp_ms` | Deterministic, doesn't drift with the live edge. |
  | "Look at frame N exactly"          | `image_url` with `frame_index=N`                           | Stable across calls; `timestamp_ms` is too.      |

  ### Idempotency

  * Stream creates aren't idempotent — there's no idempotency key. Don't auto-retry `POST /streams` until you've confirmed the previous attempt failed (no response logged).
  * Chat completions are idempotent in the sense that there are no side effects, but every retry incurs cost and emits a new `id`.
  * Deletes are idempotent: a `404` after a successful `DELETE` is fine to ignore.

  ### Watching multiple streams

  A single `messages` array can carry content parts referencing different `stream_id`s. The model sees them as separate visual contexts and can compare across them. Useful patterns:

  * **Cross-camera correlation** — pass the latest frame from each camera; ask "which view shows the package?"
  * **Triage with escalation** — small model watches every camera every 1s; on a hit, the orchestrator calls a bigger model with a longer window from just the relevant camera.
</Visibility>


# Chat Completion
Source: https://docs.overshoot.ai/chat-completion

Use an OpenAI-compatible request to interact with your stream. Reference any moment by URL: a single frame, a window, or several windows.

## Intro

If you're familiar with the Chat Completion API, feel free to skip to the next section.

The Chat Completion API is the building block of almost every AI application today. Quick refresher:

A Chat Completion Request contains primarily two attributes:

* `model`: The model the user would like to run
* `messages`: A structured chat-form representation of the prompt. Basically a list containing system messages, user messages (”user questions”), assistant messages and tool calls.

<Accordion title="Example of Chat Completion request">
  ```json request.json theme={null}
  {
    "model": "google/gemma-4-26B-A4B-it",
    "messages": [
      {
        "role": "system",
        "content": [
          {
            "type": "text",
            "text": "You are a helpful assistant."
          }
        ]
      },
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "What is the capital of France?"
          }
        ]
      },
      {
        "role": "assistant",
        "content": [
          {
            "type": "text",
            "text": "The capital of France is Paris."
          }
        ]
      },
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "How about Morocco?"
          }
        ]
      }
    ]
  }
  ```
</Accordion>

Almost all inference providers today provide Chat Completion inference endpoints. You can either call it over raw HTTP or using the `openai` SDK.

<Accordion title="Example of Chat Completion request using OpenAI python library">
  ```python theme={null}
  import os
  from openai import OpenAI

  client = OpenAI(
      base_url="https://api.overshoot.ai/v1beta",
      api_key=os.environ["OVERSHOOT_API_KEY"],
  )

  response = client.chat.completions.create(
      model="google/gemma-4-26B-A4B-it",
      messages=[
          {"role": "system", "content": "You are a helpful assistant"},
          {"role": "user", "content": "what is the capital of france?"},
          {"role": "assistant", "content": "the capital of france is paris."},
          {"role": "user", "content": "how about morocco?"},
      ],
  )

  print(response.choices[0].message.content)
  ```
</Accordion>

When the inference provider receives the request, they use the model's [chat template](https://huggingface.co/docs/transformers/en/chat_templating) to turn it into a single string and tokenize it. In the example above, the inference provider will respond with "Rabat".

For Vision Language Models (VLM), image and video data can be passed in the message content in the form of bytes or URLs.

<CodeGroup>
  ```json URL wrap theme={null}
  {
  	"role": "user",
  	"content": [
  		{
  			"type": "text",
  			"text": "how many people appeared in this video?"
  		},
  		{
  			"type": "video_url",
  			"video_url": {
  				"url": "https://example.com/video.mp4"
  			}
  		}
  	]
  }
  ```

  ```json Base 64 wrap theme={null}
  {
  	"role": "user",
  	"content": [
  		{
  			"type": "text",
  			"text": "what do you see in this picture"
  		},
  		{
  			"type": "image_url",
  			"image_url": {
  				"url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ..."
  			}
  		}
  	]
  }
  ```
</CodeGroup>

If a message contains an image / video, it will get converted into tokens and interleaved with the text.

Note: some models don't allow you to interleave text and images

## Using Overshoot with Chat Completion

When you create a stream and connect it to your camera source, Overshoot allows you to reference parts (or all) of your stream in the message content of your Chat Completion Request with a simple URL.

* Use `type=image_url` to refer to a particular frame in the video. For example, the last frame can be referenced as follows:

```json wrap theme={null}
{
	"type": "image_url", 
	"image_url": {"url": "ovs://streams/{stream_id}?frame_index=-1"}
}
```

* Use `type=video_url` to refer to a segment in the video. Unlike the frame, a video segment must have a `start` and `end` . If no `end` is specified, we default to `now`. For example, to refer to the last 5 seconds of the stream,

```json wrap theme={null}
{"type": "video_url", "video_url": {"url": "ovs://streams/{stream_id}?start_offset_ms=-5000"}}
```

* To look at the first 5 minutes of the stream, use `start_offset_ms` instead.

```json wrap theme={null}
{"type": "video_url", "video_url": {"url": "ovs://streams/{stream_id}?start_offset_ms=0&end_offset_ms=300000"}}
```

The mental model here is that when you create a `Stream` , Overshoot gives you a handle to reference any part (or all) of the stream in any conversation with any model.

That is, you can:

* Have a model look at multiple segments of the same stream in the same converstion
* The model can also watch segments from different streams at the same time
* Have small model watch the stream for a specific event and escalate it to a bigger model
* Have multiple models watch the same stream for a given event and only escalate it if event is triggered


# Glossary
Source: https://docs.overshoot.ai/glossary

Canonical definitions for Overshoot terms used across the docs and API.

Use these terms consistently when reading or writing about Overshoot. The source of truth for the wire format is [`api-reference/openapi.yaml`](/api-reference/introduction).

## Stream

A leased live-video session. A Stream holds the most recent window of frames your client publishes (up to roughly 10 minutes of buffer) and exposes them to vision-language models through the `ovs://` URI scheme.

* Created by [`POST /streams`](/api-reference/create-stream).
* Inspected by [`GET /streams/{stream_id}`](/api-reference/get-stream).
* Renewed by [`POST /streams/{stream_id}/keepalive`](/api-reference/keepalive-stream).
* Deleted by [`DELETE /streams/{stream_id}`](/api-reference/delete-stream).

A Stream ends when the lease expires (5 minutes idle) or the client deletes it. See [The Stream](/the-stream) for the full lifecycle.

## `stream_id`

UUID returned by `POST /streams`. Use this exact spelling in prose and code — not `"streamId"` or `"stream ID".` Pass it as a path parameter on stream endpoints and as part of the `ovs://` URI.

## Frame

A single image extracted from the publisher's video track and stored in the Stream's buffer. Reference an individual frame from chat completions with `frame_index` (see below).

## `frame_index`

Integer index into a Stream's retained frames.

* `frame_index=-1` — the most recent frame (typical for "what's happening right now").
* `frame_index=0` — the first frame still retained in the buffer (older frames are evicted).

Returned values include `last_frame_index`, `first_available_frame_index`, `retained_frame_count`, and `evicted_frame_count` from [`GET /streams/{stream_id}`](/api-reference/get-stream).

## Segment

A time-bounded slice of a Stream, referenced via `start_offset_ms` and optionally `end_offset_ms`.

* `start_offset_ms=-5000` means "5 seconds ago relative to the live edge".
* `start_offset_ms=0` means "the start of the available buffer".
* Omit `end_offset_ms` to mean "now".

## `ovs://` URI

Overshoot's stream-reference URI scheme. Used inside `image_url` or `video_url` content parts on `/chat/completions`.

* Frame: `ovs://streams/{stream_id}?frame_index=-1`
* Segment: `ovs://streams/{stream_id}?start_offset_ms=-5000`
* Bounded segment: `ovs://streams/{stream_id}?start_offset_ms=0&end_offset_ms=10000`

The `ovs://` URI is a reference identifier the server parses to extract `stream_id` and the query — it is not a fetchable URL. See [Chat Completion](/chat-completion) for examples.

## Lease

The keepalive window for a Stream. Default is 5 minutes from the most recent keepalive (or stream creation). When the lease expires, the Stream is deleted.

## Keepalive

The act of renewing a Stream's lease. Call [`POST /streams/{stream_id}/keepalive`](/api-reference/keepalive-stream) roughly every 2 minutes while the Stream is in use. Each keepalive returns a fresh LiveKit token you can use to rejoin the room if your publisher disconnects.

## Model id

The string you pass as the `model` field on `/chat/completions`. Format is `provider/model-name`:

* `Qwen/Qwen3.6-27B-FP8`
* `Qwen/Qwen3.6-35B-A3B-FP8`
* `google/gemma-4-26B-A4B-it`
* `google/gemma-4-31B-it`
* `Hcompany/Holo3-35B-A3B`

List currently-ready model ids with [`GET /models`](/api-reference/list-models) or browse the [Models page](/models).

## LiveKit room

The WebRTC publish target returned by `POST /streams`. Comprises a `wss://` URL and a short-lived JWT token. Connect with any [LiveKit SDK](https://docs.livekit.io/reference/) to publish your video track. Overshoot's media gateway is the only other participant in the room.

## API key

Bearer token used to authenticate requests. Prefixed with `ovs-`. Issued from the [Overshoot dashboard](https://overshoot.ai/dashboard). Only [`GET /models`](/api-reference/list-models) is unauthenticated.


# Welcome to Overshoot
Source: https://docs.overshoot.ai/intro



Overshoot enables developers to build realtime vision applications in two steps:

* Create a `/streams` session and connect a live video source to it
* Ask any model about any moment of the video stream via `/chat/completions` request

That's it. 2 HTTP stateless endpoints is all you need to build anything.

If you can't be bothered to read the documentation, here's what you need to know:

1. When you create a [Stream](/the-stream) , you get back a `Stream ID`, a LiveKit Room URL with a token. Use a LiveKit SDK to publish your video stream in the room.
2. Once a [Stream](/the-stream) is connected, you can refer to parts or all of it inside your OpenAI Compatible [Chat Completion](/chat-completion) request.
   * To refer to single frames, pass them as `image_url` inside the [message content](https://developers.openai.com/api/reference/resources/chat#\(resource\)%20chat.completions%20%3E%20\(model\)%20chat_completion_content_part%20%3E%20\(schema\)).
   ```json theme={null}
   // last frame
   {
     "type": "image_url",
     "image_url": {
       "url": "ovs://streams/{stream_id}?frame_index=-1"
     }
   }
   ```
   * Similarly, to refer to segments in the live stream, pass them as `video_url`
   ```json theme={null}
   // last 5 seconds
   {
     "type": "video_url",
     "video_url": {
       "url": "ovs://streams/{stream_id}?start_offset_ms=-5000"
     }
   }
   ```

Hope this makes sense.

Enjoy!

<CardGroup>
  <Card title="Quickstart" icon="play" href="/quickstart">
    Webcam to model in four steps.
  </Card>

  <Card title="The Stream" icon="video" href="/the-stream">
    Lifecycle, leases, and how to keep a session alive.
  </Card>

  <Card title="Chat Completion" icon="message" href="/chat-completion">
    URL grammar for referencing frames and segments.
  </Card>

  <Card title="Models" icon="microchip-ai" href="/models">
    What's available, context limits, picking the right one.
  </Card>
</CardGroup>

<Visibility>
  ## Mental model for agents

  See the [Glossary](/glossary) for canonical definitions of every term used across the docs.

  A `Stream` is a leased server-side handle for a live video feed. Once a publisher is attached (via the LiveKit room URL + token returned at creation), Overshoot ingests frames continuously and indexes them. The handle is opaque from the model's perspective — you reference moments inside the stream by URL, not by uploading bytes.

  A chat completion request is OpenAI-compatible. The only Overshoot-specific construct is the URI inside `image_url` / `video_url` content parts:

  ```
  ovs://streams/{stream_id}?<anchor>
  ```

  The `ovs://` scheme is a reference identifier — the server parses `stream_id` and the query out of it and resolves frames internally. It is not a fetchable URL.

  Where `<anchor>` is exactly one of:

  * `frame_index=N` — Nth frame of the stream's lifetime. Negative = from live edge. `frame_index=-1` is "the latest frame".
  * `timestamp_ms=N` — absolute stream-clock timestamp in ms.
  * `offset_ms=N` — offset from now, in ms. Negative = past.

  Video segments take a `start_*` anchor and an optional `end_*` anchor (defaults to live edge). Use the same field names with a `start_` / `end_` prefix.

  ## Authentication

  All endpoints except `GET /models` require a bearer token: `Authorization: Bearer ovs-...`. Keys are issued from the [dashboard](https://platform.overshoot.ai).

  ## Lifecycle invariants

  * A stream is deleted \~5 minutes after the last keepalive or after `DELETE /streams/{id}`.
  * A stream's `state` transitions only forward: `active` → `ended`. There is no resume.
  * A new keepalive returns a fresh LiveKit token; the old token may stop working when the publisher reconnects.
  * `frame_index` is monotonically increasing across the stream's lifetime, even after eviction. Old indices outside the retention window resolve to the oldest available frame (intersection-with-availability semantics).

  ## Endpoint surface

  | Method   | Path                             | Auth | Purpose                                      |
  | -------- | -------------------------------- | ---- | -------------------------------------------- |
  | `POST`   | `/v1beta/chat/completions`       | Yes  | OpenAI-compatible chat completions.          |
  | `POST`   | `/v1beta/streams`                | Yes  | Create a stream, get a LiveKit room + token. |
  | `GET`    | `/v1beta/streams/{id}`           | Yes  | Inspect stream state.                        |
  | `POST`   | `/v1beta/streams/{id}/keepalive` | Yes  | Renew lease, get a fresh token.              |
  | `DELETE` | `/v1beta/streams/{id}`           | Yes  | End the stream.                              |
  | `GET`    | `/v1beta/models`                 | No   | List available vision-language models.       |
  | `GET`    | `/billing/pricing`               | No   | List public model prices.                    |
  | `GET`    | `/billing/pricing/{model}`       | No   | Pricing for one model.                       |
  | `GET`    | `/billing/accounts/me/balance`   | Yes  | Get prepaid balance.                         |
  | `POST`   | `/billing/checkout`              | Yes  | Buy prepaid credits.                         |
</Visibility>


# Models
Source: https://docs.overshoot.ai/models

Vision Language Models on Overshoot

Overshoot serves a curated set of vision-language models tuned for real-time inference. Pick one from the [active models](#active-models) list, pass its `id` as the `model` field on `/chat/completions`, and Overshoot routes the request to a healthy endpoint.

## List available models

Availability changes as endpoints come online and go offline. Always query `/models` before starting a stream. **No auth required.**

<CodeGroup>
  ```shellscript curl theme={null}
  curl https://api.overshoot.ai/v1beta/models
  ```

  ```python python theme={null}
  import httpx

  r = httpx.get("https://api.overshoot.ai/v1beta/models")
  ready = [m for m in r.json()["data"] if m["status"] == "ready"]
  for m in ready:
      print(m["id"])
  ```

  ```typescript typescript theme={null}
  const res = await fetch("https://api.overshoot.ai/v1beta/models");
  const { data } = await res.json();
  const ready = data.filter((m) => m.status === "ready");
  ```
</CodeGroup>

The response is OpenAI-compatible — same shape `listModels` returns, with one extra `status` field per entry.

<Accordion title="Sample response">
  ```json theme={null}
  {
    "object": "list",
    "data": [
      {
        "id": "Qwen/Qwen3.6-27B-FP8",
        "object": "model",
        "created": 1714492800,
        "owned_by": "overshoot",
        "status": "ready"
      },
      {
        "id": "google/gemma-4-31B-it",
        "object": "model",
        "created": 1714492800,
        "owned_by": "overshoot",
        "status": "ready"
      }
    ]
  }
  ```
</Accordion>

## Active models

<Info>
  Snapshot as of **2026-06-16**. The `/models` endpoint is the source of truth — treat these tables as a quick reference, not a guarantee.
</Info>

Models on Overshoot fall into two groups: **Overshoot-hosted** (open-weights models we run on our own GPU fleet, tuned for real-time inference) and **proprietary passthrough** (Gemini / Claude / OpenAI, which we proxy to the upstream provider). Default to the hosted models — that's where Overshoot's latency advantage lives.

### Overshoot-hosted

These are the fast path. We run them on our own GPUs, sized for sub-second time-to-first-token on single-frame inputs and high-throughput video.

| Model                       | Provider  | Context | Tokens / frame              | Max frames              |
| --------------------------- | --------- | ------- | --------------------------- | ----------------------- |
| `Qwen/Qwen3.6-27B-FP8`      | Qwen      | 32K     | \~200 @ 480p                | Capped by context       |
| `Qwen/Qwen3.6-35B-A3B-FP8`  | Qwen      | 16K     | \~200 @ 480p                | Capped by context (16K) |
| `google/gemma-4-31B-it`     | Google    | 256K    | 70 / 140 / 280 / 560 / 1120 | \~60 (1 fps × 60 s)     |
| `google/gemma-4-26B-A4B-it` | Google    | 256K    | 70 / 140 / 280 / 560 / 1120 | \~60 (1 fps × 60 s)     |
| `Hcompany/Holo3-35B-A3B`    | H Company | 16K     | \~200 @ 480p                | Capped by context (16K) |

### Proprietary passthrough

These are upstream APIs we expose through the same OpenAI-compatible surface for convenience. **They are not part of Overshoot's real-time path.**

<Warning>
  Proprietary models are passthrough to Google / Anthropic / OpenAI. Time-to-first-token is bounded by the upstream provider — typically **seconds**, not the sub-second latency Overshoot-hosted models hit. Reach for these only when you specifically need a frontier proprietary model; otherwise stay on the hosted list.
</Warning>

| Model                       | Upstream      | Modalities   | Notes                                |
| --------------------------- | ------------- | ------------ | ------------------------------------ |
| `gemini-3-flash-preview`    | Google Gemini | image, video | Fast Gemini tier                     |
| `gemini-3.1-pro-preview`    | Google Gemini | image, video | Frontier reasoning, lowest RPM quota |
| `claude-haiku-4-5-20251001` | Anthropic     | image only   | Fastest Claude tier (no video)       |
| `claude-sonnet-4-6`         | Anthropic     | image only   |                                      |
| `claude-opus-4-6`           | Anthropic     | image only   | Highest capability, highest latency  |
| `gpt-5.4-nano`              | OpenAI        | image only   | Cheapest GPT-5 tier                  |
| `gpt-5.4-mini`              | OpenAI        | image only   |                                      |
| `gpt-5.4`                   | OpenAI        | image only   |                                      |

### How to read the columns

<AccordionGroup>
  <Accordion title="Context — served vs native" icon="ruler">
    **Served** is the context length we run the model with.
  </Accordion>

  <Accordion title="Tokens / frame — Qwen models" icon="image">
    Qwen3.6 uses the same image processor as the Qwen3 line: patch 16, `temporal_patch_size=2`, `spatial_merge_size=2`. The formula:

    ```text theme={null}
    tokens_per_frame ≈ (H × W) / 2048
    ```

    | Resolution        | Tokens / frame |
    | ----------------- | -------------- |
    | 480p (854×480)    | \~200          |
    | 720p (1280×720)   | \~450          |
    | 1080p (1920×1080) | \~1010         |

    Numbers in the table assume 480p — the resolution our benchmark suite uses. Higher resolutions consume context faster.
  </Accordion>

  <Accordion title="Tokens / frame — Gemma 4" icon="sliders">
    You pick the visual-token budget per request — `70`, `140`, `280`, `560`, or `1120`:

    * **70–280** — classification, captioning, video understanding.
    * **560–1120** — OCR, document parsing, small text.

    Default is 256 tokens.
  </Accordion>

  <Accordion title="Max frames" icon="film">
    * **Qwen / Holo3** — no hard model-side cap. Frame count is bounded by context. The practical limit is `(context − text_input − text_output) / tokens_per_frame`.
    * **Gemma 4** — Google documents 60 s at 1 fps as the supported envelope (\~60 frames).
  </Accordion>

  <Accordion title="Interleaved text + video" icon="layer-group">
    The model can mix text segments between visual tokens inside a single message — instead of forcing all visual content into one block followed by text. Every active model supports this.
  </Accordion>
</AccordionGroup>

## Use a model

Pass the `id` from `/models` straight into `/chat/completions`:

```shellscript wrap theme={null}
curl -X POST https://api.overshoot.ai/v1beta/chat/completions \
  -H "Authorization: Bearer $OVERSHOOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3.6-27B-FP8",
    "messages": [{
      "role": "user",
      "content": [
        { "type": "text", "text": "What is the person doing?" },
        { "type": "image_url", "image_url": {
            "url": "ovs://streams/$STREAM_ID?frame_index=-1"
        }}
      ]
    }]
  }'
```

See [Chat Completion](/chat-completion) for the full request/response shape.

<Visibility>
  ## Routing and selection — for agents

  <Warning>
    **Speed-first rule.** Always start with an Overshoot-hosted model. Proprietary passthrough models (any `gemini-*`, `claude-*`, `gpt-*` id) are slower — TTFT is bounded by the upstream provider and is typically seconds, not sub-second. Pick a proprietary model only when the user has explicitly asked for that family or you have ruled out every hosted option for the workload. Do not default to Gemini / Claude / OpenAI just because the names are familiar.
  </Warning>

  ### Selection algorithm

  1. `GET /v1beta/models`. The response is a list. Filter to entries with `status == "ready"`.
  2. **Filter to Overshoot-hosted first.** A model is hosted if its `id` looks like `<owner>/<model>` (e.g. `Qwen/...`, `google/gemma-...`, `Hcompany/...`). Anything else (`gemini-*`, `claude-*`, `gpt-*`) is proprietary passthrough — slower, only use as a deliberate fallback.
  3. From the hosted set, pick a model `id` whose properties match the workload (see the table above).
  4. Use that exact `id` as the `model` field in `/chat/completions`.

  ### Status values

  | Status        | Meaning                                  | What to do                                                |
  | ------------- | ---------------------------------------- | --------------------------------------------------------- |
  | `ready`       | At least one healthy replica is serving. | Use it.                                                   |
  | `unavailable` | Currently not serving.                   | Don't use — retry later or fall through to another model. |

  A model that's `ready` at list-time can return `503` at completion-time if the only replica fell over between calls. Always handle `503` with either a retry or a fallback to another `ready` model.

  ### Cost / latency tradeoff

  Visual tokens dominate prompt size for video workloads. The relevant knobs:

  * **Resolution** — drop from 1080p to 480p and Qwen prompt tokens fall \~5×.
  * **Frames** — half the frames = roughly half the tokens.
  * **Per-frame budget (Gemma only)** — `70` is fine for "what's happening" questions; reserve `560`+ for OCR.

  ### Fallback chains that work in practice

  All chains stay inside the Overshoot-hosted set. Only fall through to a proprietary model if the entire hosted chain is `503` *and* the user is willing to accept seconds-of-TTFT latency.

  * *Best-quality video understanding* — `Qwen/Qwen3.6-27B-FP8` → `google/gemma-4-31B-it`.
  * *MoE high-throughput vision* — `Qwen/Qwen3.6-35B-A3B-FP8` → `google/gemma-4-26B-A4B-it`.
  * *Document / OCR-style frames* — `google/gemma-4-31B-it` (with `1120` per-frame) → `google/gemma-4-26B-A4B-it` (with `1120` per-frame).
  * *GUI / agent screenshots* — `Hcompany/Holo3-35B-A3B` → `Qwen/Qwen3.6-27B-FP8`.
  * *Last-resort proprietary fallback (slow)* — `gemini-3-flash-preview` → `claude-haiku-4-5-20251001`. Only after every hosted option above has failed.

  ### Programmatic listing — hosted only

  Hosted model IDs always contain a `/` (`<owner>/<model>`). Proprietary IDs do not. Use that to keep agents on the fast path by default:

  ```python theme={null}
  import httpx

  resp = httpx.get("https://api.overshoot.ai/v1beta/models", timeout=5)
  resp.raise_for_status()
  ready = [m["id"] for m in resp.json()["data"] if m["status"] == "ready"]
  hosted = [m for m in ready if "/" in m]              # fast path — prefer these
  proprietary = [m for m in ready if "/" not in m]     # slow fallback — gemini-*, claude-*, gpt-*
  ```

  ```typescript theme={null}
  const res = await fetch("https://api.overshoot.ai/v1beta/models");
  if (!res.ok) throw new Error(`models: ${res.status}`);
  const { data } = (await res.json()) as { data: Array<{ id: string; status: string }> };
  const ready = data.filter((m) => m.status === "ready").map((m) => m.id);
  const hosted = ready.filter((id) => id.includes("/"));         // fast path
  const proprietary = ready.filter((id) => !id.includes("/"));   // slow fallback
  ```
</Visibility>


# Quickstart
Source: https://docs.overshoot.ai/quickstart

Get started in four quick steps

<Steps>
  <Step title="Authenticate">
    <Card title="Get your API Key" icon="key" href="https://platform.overshoot.ai/api-keys" />
  </Step>

  <Step title="Create a stream">
    We call the `/streams` endpoint to create a [Stream](/the-stream).

    <FillerCard>
      <TextFiller placeholder="$OVERSHOOT_API_KEY" label="Paste your API key — auto-fills the snippets below" />
    </FillerCard>

    ```shellscript theme={null}
    curl -X POST https://api.overshoot.ai/v1beta/streams \
    -H "Authorization: Bearer $OVERSHOOT_API_KEY"
    ```

    The command above returns a Room URL and a Token. Save those for the next step.

    <Accordion title="Sample Response">
      ```json focus={2,6-7} theme={null}
      {
          "id": "2ea5a604-d225-4cd2-82ac-b907cb0b4f63",
          "state": "active",
          "publish": {
              "type": "livekit",
              "url": "wss://livekit.overshoot.ai",
              "token": "ey...k"
          },
          "expires_at_ms": 1777529931184,
          "ttl_seconds": 300
      }
      ```
    </Accordion>
  </Step>

  <Step title="Connect your webcam to the stream">
    Paste your Room URL and Token to generate a one-click [LiveKit Meet](https://meet.livekit.io/?tab=custom) link, or use your favorite [LiveKit SDK](https://docs.livekit.io/transport/sdk-platforms/).

    <LiveKitConnector />
  </Step>

  <Step title="Ask the model what it can see">
    Once the camera is connected, send a simple [Chat Completion](/chat-completion) request to the model.

    <FillerCard>
      <ModelFiller placeholder="google/gemma-4-26B-A4B-it" label="Model — pulled live from the API" />

      <TextFiller placeholder="{stream_id}" label="Stream ID — from the response above" />
    </FillerCard>

    ```shellscript highlight={12} wrap theme={null}
    curl -X POST https://api.overshoot.ai/v1beta/chat/completions \
    -H "Authorization: Bearer $OVERSHOOT_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
    "model": "google/gemma-4-26B-A4B-it",
    "messages": [
        {
        "role": "user",
        "content": [
            {"type": "text", "text": "What am I wearing?"},
            {"type": "image_url", "image_url": {
                "url": "ovs://streams/{stream_id}?frame_index=-1"
            }}
        ]
        }]}'
    ```

    <Accordion title="Sample Response">
      ```json theme={null}
      {
          "id": "34225b75-abae-4c58-8191-2abdc8f437de",
          "object": "chat.completion",
          "created": 1777530304,
          "model": "google/gemma-4-26B-A4B-it",
          "choices": [
              {
                  "index": 0,
                  "message": {
                      "role": "assistant",
                      "content": "Plaid robe, t-shirt."
                  },
                  "finish_reason": "stop"
              }
          ],
          "usage": {
              "prompt_tokens": 307,
              "completion_tokens": 9,
              "total_tokens": 316
          }
      }
      ```
    </Accordion>
  </Step>
</Steps>


# The Stream
Source: https://docs.overshoot.ai/the-stream

A leased session that holds your live video feed and makes it addressable from any chat completion.

The core primitive in Overshoot is the `Stream`.

Clients connect any live video source to Overshoot via the `Stream`. Creating one is straightforward — call `/streams` with an API key:

```shellscript theme={null}
curl -X POST https://api.overshoot.ai/v1beta/streams \
  -H "Authorization: Bearer $OVERSHOOT_API_KEY"
```

This returns a `stream_id` and a [LiveKit room](https://docs.livekit.io/intro/basics/rooms-participants-tracks/rooms/). Use any [LiveKit SDK](https://docs.livekit.io/reference/) to join the room and publish your video into it. Our media gateway joins the same room, ingests your stream, and prepares it for inference.

<Accordion title="Sample response">
  ```json focus={2-3,5-9} theme={null}
  {
    "id": "2ea5a604-d225-4cd2-82ac-b907cb0b4f63",
    "state": "active",
    "publish": {
      "type": "livekit",
      "url": "wss://livekit.overshoot.ai",
      "token": "ey...k"
    },
    "expires_at_ms": 1777529931184,
    "ttl_seconds": 300
  }
  ```
</Accordion>

A `Stream` holds the state of your live feed **as long as it's alive**. Read on for how to keep one alive, and how to kill it.

## Stream state

The `Stream` holds your video as long as it's alive. If you push no frames, it sits empty.

To check the state (e.g. frames received, recent FPS, time to expiry, etc.), call:

```shellscript theme={null}
curl https://api.overshoot.ai/v1beta/streams/{stream_id} \
  -H "Authorization: Bearer $OVERSHOOT_API_KEY"
```

<Accordion title="Sample response">
  ```json theme={null}
  {
    "id": "2ea5a604-d225-4cd2-82ac-b907cb0b4f63",
    "state": "active",
    "stream_time_ms": 12480,
    "first_frame_at_ms": 1777529631184,
    "last_frame_at_ms":  1777529643664,
    "last_frame_index": 312,
    "recent_fps": 25.0,
    "retained_frame_count": 312,
    "evicted_frame_count": 0,
    "expires_at_ms": 1777529931184,
    "ttl_seconds": 300
  }
  ```
</Accordion>

A `Stream` ends when it expires (5 min idle) or gets `DELETE`d. Once `state` flips to `ended`, it stays ended — there is no resume.

## How to keep a stream alive

When Overshoot starts ingesting your stream, we run a fair amount of processing in the background to make every frame available for any model. To avoid leaking sessions, a stream will expire after 5 minutes. To keep it alive, call `/keepalive` with your `stream_id` regularly. Every 2 minutes is a safe cadence.

```shellscript theme={null}
curl -X POST https://api.overshoot.ai/v1beta/streams/{stream_id}/keepalive \
  -H "Authorization: Bearer $OVERSHOOT_API_KEY"
```

Each keepalive returns a fresh LiveKit token. Save it — if your publisher disconnects from the room, you'll need it to rejoin without recreating the stream.

## How to kill a stream

`DELETE` it.

```shellscript theme={null}
curl -X DELETE https://api.overshoot.ai/v1beta/streams/{stream_id} \
  -H "Authorization: Bearer $OVERSHOOT_API_KEY"
```

<Visibility>
  ## Lifecycle, in detail

  ### States

  A `Stream` has exactly two states:

  * `active` — created, accepting publishers and inference. The default for any newly-created stream.
  * `ended` — terminal. Set once on TTL expiry or explicit delete. Never transitions back.

  `GET /streams/{id}` continues to return ended streams for a short tombstone window with `state: "ended"`, `ended_at_ms`, and `end_reason`. After the tombstone window the endpoint returns `404`.

  ### TTL and keepalive

  * Default TTL: **300 seconds** (`ttl_seconds: 300`) from the most recent of: creation, keepalive, or last activity signal.
  * Each successful `POST /keepalive` resets the lease to `now + ttl_seconds` and returns a new `expires_at_ms` plus a fresh LiveKit `token`.
  * Recommended polling cadence: every 60–120s. Don't rely on TTL minus one second; clock skew between caller and server is real.
  * A stream with `state: "ended"` cannot be revived by a keepalive. Create a new stream instead.

  ### Stream status fields

  | Field                         | Type    | Notes                                                     |
  | ----------------------------- | ------- | --------------------------------------------------------- |
  | `id`                          | uuid    | Stable for the lifetime of the stream.                    |
  | `state`                       | enum    | `active` \| `ended`.                                      |
  | `stream_time_ms`              | float   | Stream-clock position in ms — monotonic from first frame. |
  | `first_frame_at_ms`           | int     | Wall-clock ms of the first frame ingested.                |
  | `last_frame_at_ms`            | int     | Wall-clock ms of the most recent frame.                   |
  | `last_frame_index`            | int     | Lifetime-indexed position of the most recent frame.       |
  | `first_available_frame_at_ms` | int     | Wall-clock ms of the oldest retained frame.               |
  | `first_available_frame_index` | int     | Lifetime index of the oldest retained frame.              |
  | `recent_fps`                  | float   | Rolling FPS over the last few seconds of ingest.          |
  | `retained_frame_count`        | int     | Frames currently retained in the buffer.                  |
  | `evicted_frame_count`         | int     | Frames that have aged out of retention.                   |
  | `created_at_ms`               | int     | Wall-clock ms of stream creation.                         |
  | `expires_at_ms`               | int     | Wall-clock ms when the lease will expire if not renewed.  |
  | `ttl_seconds`                 | int     | Configured TTL — currently 300 for all streams.           |
  | `ended_at_ms`                 | int?    | Set when `state == "ended"`.                              |
  | `end_reason`                  | string? | `expired` \| `deleted`.                                   |
  | `audio`                       | bool    | Reserved. Always `false`.                                 |

  ### Frame indexing semantics

  `frame_index` is monotonically increasing across the stream's lifetime. It is *not* reset by eviction. If you reference a `frame_index` that's older than `first_available_frame_index`, the URL resolver clamps to `first_available_frame_index` (intersection-with-availability semantics) — your request succeeds against the oldest frame still in the buffer. The same applies to `start_frame_index` for video segments.

  Negative indices are interpreted relative to `last_frame_index` at request time: `frame_index=-1` is "most recent", `-2` is the one before, and so on.

  ### Errors

  | Code        | Meaning                                                                             |
  | ----------- | ----------------------------------------------------------------------------------- |
  | `401`/`403` | Missing or invalid API key.                                                         |
  | `402`       | Insufficient credits to create a new stream.                                        |
  | `404`       | Stream not found, ended past the tombstone window, or owned by a different API key. |
  | `503`       | Ingest service draining or starting up — retry with backoff.                        |
</Visibility>

