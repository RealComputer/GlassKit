# Rokid WebRTC

The common pattern is:

1. Android captures camera and/or microphone media.
2. Android creates a WebRTC offer.
3. Android sends the offer to a backend or service broker.
4. The backend returns an answer SDP.
5. Android sets the remote description and keeps HUD/control state outside the media track.

Android should receive URLs, session ids, SDP answers, and normalized app events.

## Integration Shapes

Common patterns:

- **Backend media receiver**: Android sends an SDP offer to your backend. If the backend is Python, use `aiortc` to create the peer connection, receive tracks, create an answer, and send app state back on a data channel.
- **Backend service broker**: Android sends an SDP offer to your backend. The backend creates an upstream vendor stream/call, returns the vendor answer SDP, and relays service events to Android. This fits realtime media APIs.

Use `aiortc` for Python backend code that terminates WebRTC or needs to generate a local answer SDP. Provider brokers that only forward Android's offer to an upstream service may not need local WebRTC objects.

## Android Setup

Use Stream's WebRTC package. This is the known working version:

```kotlin
implementation("io.getstream:stream-webrtc-android:1.3.10")
```

Most clients also use OkHttp and coroutines for signaling. Prefer the app's existing versions; these versions are known to work:

```kotlin
implementation("com.squareup.okhttp3:okhttp:4.12.0")
implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
```

Manifest permissions depend on the tracks:

```xml
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
<uses-permission android:name="android.permission.WAKE_LOCK" />
```

Request `RECORD_AUDIO` only when Android captures local microphone audio. Receive-only remote audio playback and transcript rendering do not need `RECORD_AUDIO`.

Use `android:usesCleartextTraffic="true"` only for local `http://` development backends.

Create and release these explicitly:

- `EglBase`
- `PeerConnectionFactory`
- `PeerConnection`
- video capturer and `SurfaceTextureHelper`
- local audio/video sources and tracks
- data channels
- WebSocket or HTTP signaling clients
- `JavaAudioDeviceModule` if WebRTC owns microphone or speaker routing

## Peer Connection Factory

Initialize WebRTC once per client lifecycle and reuse one `PeerConnectionFactory` for a session client:

```kotlin
private val eglBase: EglBase = EglBase.create()

private fun createPeerConnectionFactory(): PeerConnectionFactory {
    PeerConnectionFactory.initialize(
        PeerConnectionFactory.InitializationOptions.builder(context)
            .createInitializationOptions()
    )

    val encoderFactory = DefaultVideoEncoderFactory(
        eglBase.eglBaseContext,
        /* enableIntelVp8Encoder = */ true,
        /* enableH264HighProfile = */ true
    )
    val decoderFactory = DefaultVideoDecoderFactory(eglBase.eglBaseContext)

    return PeerConnectionFactory.builder()
        .setVideoEncoderFactory(encoderFactory)
        .setVideoDecoderFactory(decoderFactory)
        .createPeerConnectionFactory()
}
```

If the session includes microphone capture or remote audio playback, add a Rokid-friendly audio module:

```kotlin
val audioDeviceModule = JavaAudioDeviceModule.builder(context)
    .setSampleRate(16_000)
    .setUseHardwareAcousticEchoCanceler(false)
    .setUseHardwareNoiseSuppressor(false)
    .setUseStereoInput(false)
    .setUseStereoOutput(false)
    .setAudioAttributes(
        AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
    )
    .setAudioSource(MediaRecorder.AudioSource.MIC)
    .createAudioDeviceModule()
```

Then pass it to the factory builder with `.setAudioDeviceModule(audioDeviceModule)`. The `USAGE_MEDIA` route and disabled hardware AEC/NS avoid Rokid vendor VOIP-path issues during simultaneous capture and playback.

## Peer Connection Config

Use Unified Plan:

```kotlin
val config = PeerConnection.RTCConfiguration(iceServers).apply {
    sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
}
```

Set offer constraints from the session's real media needs:

```kotlin
val mediaConstraints = MediaConstraints().apply {
    mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "false"))
    mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "false"))
}
```

Set `OfferToReceiveAudio` to `"true"` only when Android should receive speech or other remote audio. Under Unified Plan, also add a receive-only audio transceiver before creating the offer so the local SDP contains an `m=audio` section:

```kotlin
val init = RtpTransceiver.RtpTransceiverInit(
    RtpTransceiver.RtpTransceiverDirection.RECV_ONLY
)
val transceiver = peerConnection.addTransceiver(
    MediaStreamTrack.MediaType.MEDIA_TYPE_AUDIO,
    init
) ?: error("Failed to add receive-only audio transceiver")
transceiver.receiver.track()?.setEnabled(true)
```

For remote-audio-required sessions, fail fast if the local offer SDP does not contain an `m=audio` section.

Most Rokid vision streams do not receive remote video.

## Video Capture

Rokid Glasses have a single rear/outward camera. With Stream WebRTC, create a capturer from the available `Camera2Enumerator` device names:

```kotlin
private fun createCameraCapturer(): VideoCapturer? {
    val enumerator = Camera2Enumerator(context)
    for (name in enumerator.deviceNames) {
        enumerator.createCapturer(name, null)?.let { return it }
    }
    return null
}
```

For CameraX preview code, apply the Application-level back-camera limiter from [Rokid Inputs](rokid-inputs.md), bind `CameraSelector.DEFAULT_BACK_CAMERA`, request `1024x768 @ 15 fps`, and set display rotation so the landscape sensor stream appears correctly in the portrait HUD.

Rokid's camera HAL does not reliably advertise sub-15 fps modes. Start capture at a supported mode such as `1024x768 @ 15 fps`, then use source adaptation to lower the outbound WebRTC rate when needed.

For example, capture at 15 fps and send about 5 fps:

```kotlin
val source = peerConnectionFactory.createVideoSource(videoCapturer.isScreencast).apply {
    adaptOutputFormat(1024, 768, 5)
}
localVideoSource = source

videoCapturer.initialize(surfaceTextureHelper, context, source.capturerObserver)
videoCapturer.startCapture(1024, 768, 15)
```

If the camera HAL rejects the desired low FPS or resolution, start capture with a supported mode and use `adaptOutputFormat(...)` to limit what WebRTC sends.

Avoid WebRTC silently lowering the video sender quality:

```kotlin
private fun configureVideoSender(sender: RtpSender?) {
    val params = sender?.parameters ?: return
    params.degradationPreference = RtpParameters.DegradationPreference.DISABLED
    sender.parameters = params
}
```

## Audio Tracks

For WebRTC microphone streaming:

```kotlin
localAudioSource = peerConnectionFactory.createAudioSource(MediaConstraints())
localAudioTrack = peerConnectionFactory.createAudioTrack("audio0", localAudioSource)
localAudioTrack?.setEnabled(true)
localAudioTrack?.let { peerConnection.addTrack(it) }
```

Request `RECORD_AUDIO` before starting. If the backend controls when speech plays, Android should receive audio and render transcripts, but the backend should decide exactly what to say and when.

## Offer And Answer

Create all local tracks and data channels before creating the offer:

```kotlin
val offer = peerConnection.createOffer(sdpConstraints).await()
peerConnection.setLocalDescription(offer).await()
waitForIceGatheringComplete(peerConnection)

val answerSdp = postOfferToBackend(peerConnection.localDescription.description)
peerConnection.setRemoteDescription(
    SessionDescription(SessionDescription.Type.ANSWER, normalizeSdp(answerSdp))
).await()
```

Use non-trickle signaling: wait for ICE gathering, then send the complete SDP. Add a timeout of about 15 seconds if the upstream service accepts partial candidates and you prefer startup over waiting indefinitely.

Use one of these endpoint contracts:

- `Content-Type: application/sdp`: request body is raw offer SDP, response body is raw answer SDP.
- `Content-Type: application/json`: request body contains `{ "offer_sdp": "..." }`, response contains `{ "answer_sdp": "...", "session_id": "..." }`.

Normalize answer SDP before `setRemoteDescription`, especially when it came through JSON:

```kotlin
private fun normalizeSdp(raw: String): String {
    val text = raw.trim()
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace('\r', '\n')

    val lines = text
        .split('\n')
        .map { it.trim() }
        .filter { it.isNotEmpty() }

    return if (lines.isEmpty()) "" else lines.joinToString("\r\n", postfix = "\r\n")
}
```

Validate backend responses: an SDP answer should be non-empty and start with `v=`.

## Data Channels

Use a stable label per logical channel, for example `vision-events` or `session-events`. Create client-originated channels before the offer:

```kotlin
val dc = peerConnection.createDataChannel("vision-events", DataChannel.Init())
```

Use text JSON messages with a `type` field. Ignore binary messages unless the app has a specific binary protocol.

Queue client messages until the channel is open:

```kotlin
private fun sendJson(payload: JSONObject) {
    val message = payload.toString()
    val channel = dataChannel
    if (channel != null && channel.state() == DataChannel.State.OPEN) {
        channel.send(DataChannel.Buffer(ByteBuffer.wrap(message.toByteArray()), false))
    } else {
        pendingMessages.addLast(message)
    }
}
```

Flush in `onStateChange` when state becomes `DataChannel.State.OPEN`. Backend data channel handlers should send initial app state after the channel opens, then broadcast normalized state updates. Android should parse known `type` values and ignore unknown ones.

## ICE Servers

For a backend reachable on the same network or a public WebRTC endpoint, STUN is often enough:

```kotlin
PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer()
```

Some hosted media services require service-specific TURN servers. Fetch TURN URLs and credentials from your backend or the provider's session response when possible. Keep provider-specific TURN constants in provider-specific references or configuration, not in this generic WebRTC helper.

## Backend Receiver Pattern

For Python backends that receive media directly, use `aiortc`. Do not hand-roll SDP parsing or media transport:

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
        attach_app_events(channel)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return Response(content=pc.localDescription.sdp, media_type="application/sdp")
```

Close peer connections on `failed`, `closed`, or `disconnected`. For CV inference, consume the latest frame rather than queueing every frame; stale frame queues make HUD state lag behind reality.

## Backend Broker Pattern

For hosted media services, the backend usually translates Android's offer into a provider-specific session:

```python
@app.post("/vision/session")
async def create_vision_session(payload: VisionSessionCreateRequest) -> VisionSessionCreateResponse:
    offer_sdp = payload.offer_sdp.strip()
    if not offer_sdp:
        raise HTTPException(status_code=422, detail="offer_sdp must not be empty")

    upstream = await provider.create_stream(offer_sdp)
    answer_sdp = normalize_sdp(upstream.answer_sdp)

    if not answer_sdp.startswith("v="):
        raise HTTPException(status_code=502, detail="provider returned invalid answer SDP")

    session_id = store_session(upstream)
    return VisionSessionCreateResponse(session_id=session_id, answer_sdp=answer_sdp)
```

If the provider emits results through its own WebSocket, relay normalized JSON to Android over your control WebSocket, events WebSocket, or data channel. Do not make Android interpret raw provider prose or provider-specific event envelopes unless the app is intentionally provider-specific.

## Lifecycle

A session client should be single-start and idempotent-stop:

- Ignore duplicate `start()` calls while `peerConnection` is non-null.
- Stop on explicit user exit and Android `onStop()`.
- Close event WebSockets before disposing the peer connection.
- Tell the backend to close provider streams or media sessions when the app stops.
- Stop and dispose the capturer before disposing `SurfaceTextureHelper`.
- Dispose tracks and sources before disposing `PeerConnectionFactory` and `EglBase`.
- Clear queued data-channel messages on stop.

Surface connection state to the HUD:

- `NEW` / `CHECKING`: starting.
- `CONNECTED` / `COMPLETED`: live.
- `DISCONNECTED` / `FAILED`: connection lost; stop or retry from a clean session.
- `CLOSED`: stopped.

## Local Development

For `http://` backends on the development machine, either enable cleartext traffic or expose HTTPS.
