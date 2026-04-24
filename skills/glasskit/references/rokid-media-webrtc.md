# Rokid Media And WebRTC

Use this when streaming Rokid camera or microphone media to a backend, OpenAI Realtime, Overshoot, or an RF-DETR service.

## Android Dependency

The Android clients use Stream's WebRTC package:

```kotlin
implementation("io.getstream:stream-webrtc-android:1.3.10")
```

Create and release these explicitly:

- `EglBase`
- `PeerConnectionFactory`
- `PeerConnection`
- video capturer and `SurfaceTextureHelper`
- local audio/video tracks
- data channels
- WebSocket or HTTP signaling clients

## Video Capture Rates

Use the lowest useful rate for the job:

- 1024x768 at 5 fps for backend object detection where latency and battery matter more than smoothness.
- 1024x768 at 15 fps for live vision services that expect clip-like video.
- Prefer 4:3 capture because it matches the camera and HUD assumptions better than widescreen.

## Audio Modes

For direct mic streaming to OpenAI Realtime, create an audio source/track through `JavaAudioDeviceModule`. The Android client pattern uses 16 kHz mono capture and disables hardware AEC/NS where needed for predictable glasses audio.

For backend-controlled speech playback, Android should create a receive-only audio transceiver and let the backend decide exactly when OpenAI speaks.

## SDP Signaling Shape

The common Android flow:

```kotlin
val offer = peerConnection.createOffer(sdpConstraints).await()
peerConnection.setLocalDescription(offer).await()
waitForIceGatheringComplete()

val answerSdp = postOfferToBackend(peerConnection.localDescription.description)
peerConnection.setRemoteDescription(
    SessionDescription(SessionDescription.Type.ANSWER, normalizeSdp(answerSdp))
).await()
```

Use `application/sdp` for direct SDP endpoints. Use JSON like `{ "offer_sdp": "..." }` when the backend endpoint is a broker that returns `{ "answer_sdp": "..." }`.

Normalize remote SDP before setting it:

```kotlin
private fun normalizeSdp(sdp: String): String {
    return sdp.replace("\r\n", "\n").trim() + "\r\n"
}
```

## Data Channels

Use stable labels:

- `oai-events` for OpenAI Realtime event JSON.
- `vision-events` for backend detection, config, and state JSON.

If Android sends messages before the data channel is open, queue them and flush on `DataChannel.State.OPEN`.

## ICE Servers

For backend or OpenAI broker flows, STUN is usually enough:

```kotlin
PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer()
```

For Overshoot video streams, use the Overshoot TURN servers:

```kotlin
private fun createTurnIceServer(url: String): PeerConnection.IceServer {
    return PeerConnection.IceServer.builder(url)
        .setUsername("overshoot")
        .setPassword("overshoot")
        .createIceServer()
}

val iceServers = listOf(
    createTurnIceServer("turn:turn.overshoot.ai:3478?transport=udp"),
    createTurnIceServer("turn:turn.overshoot.ai:3478?transport=tcp"),
    createTurnIceServer("turns:turn.overshoot.ai:443?transport=udp"),
    createTurnIceServer("turns:turn.overshoot.ai:443?transport=tcp")
)
```

## Local Backends

If Android calls `http://...` during development, enable cleartext traffic for the app or expose the backend through HTTPS. Keep API keys on the backend even for local prototypes.
