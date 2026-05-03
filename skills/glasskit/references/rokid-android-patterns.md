# Rokid Android Patterns

## Touchpad

Rokid Glasses touchpad gestures are primarily delivered to Android as key events.

| Rokid touchpad action | Android key event | Typical app action |
| --- | --- | --- |
| Tap | `KeyEvent.KEYCODE_ENTER` | Select / confirm |
| Double-tap | None used | Back / cancel |
| Swipe forward | `KeyEvent.KEYCODE_DPAD_DOWN` | Next / move focus forward |
| Swipe backward | `KeyEvent.KEYCODE_DPAD_UP` | Previous / move focus backward |

Double-tap arrives as Android Back. Keep Back behavior centralized so inner-screen navigation and root-screen exit behavior stay consistent.

For actual implementation example and optional phone/emulator touch fallback, `../assets/rokid-hello-world/`.

## Permissions And Lifecycle

- Request only the permissions needed by the current app: camera, microphone, or none.
- Add `FLAG_KEEP_SCREEN_ON` while the HUD is active.
- Stop CameraX, WebRTC, Vosk, `AudioRecord`, WebSockets, and backend sessions in `onStop` or `onDestroy`.
- Keep root-screen Back available so users can exit the app. Either delegate to Android system Back or handle an explicit quit flow.

```kotlin
override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
}

override fun onDestroy() {
    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    super.onDestroy()
}
```

## CameraX Preview

Use this shape for a local preview test before adding WebRTC:

```kotlin
private val requestedCameraSize = Size(1024, 768)
private val requestedFps = Range(5, 5)

private fun buildPreview(previewView: PreviewView): Preview {
    val builder = Preview.Builder()
        .setTargetRotation(previewView.display?.rotation ?: Surface.ROTATION_0)
        .setResolutionSelector(
            ResolutionSelector.Builder()
                .setResolutionStrategy(
                    ResolutionStrategy(
                        requestedCameraSize,
                        ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER
                    )
                )
                .build()
        )

    Camera2Interop.Extender(builder).setCaptureRequestOption(
        CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,
        requestedFps
    )
    return builder.build()
}
```

Bind with `CameraSelector.DEFAULT_BACK_CAMERA`. The physical camera stream is landscape in sensor space; setting target rotation is important for a portrait HUD.

If exact 1024x768 at 5 fps fails, retry without the exact FPS, then without the target resolution.

## Local Voice Commands

For offline command words, use Vosk with a small grammar rather than free dictation:

```kotlin
private const val SAMPLE_RATE_HZ = 16_000

val grammar = JSONArray().apply {
    put("select")
    put("back")
    put("next")
    put("previous")
    put("[unk]")
}.toString()

val recognizer = Recognizer(model, SAMPLE_RATE_HZ.toFloat(), grammar).apply {
    setWords(false)
    setPartialWords(false)
    setEndpointerDelays(5.0f, 0.25f, 3.0f)
}
```

Read audio as 16 kHz mono PCM:

```kotlin
val minBufferBytes = AudioRecord.getMinBufferSize(
    SAMPLE_RATE_HZ,
    AudioFormat.CHANNEL_IN_MONO,
    AudioFormat.ENCODING_PCM_16BIT
)

val record = AudioRecord(
    MediaRecorder.AudioSource.MIC,
    SAMPLE_RATE_HZ,
    AudioFormat.CHANNEL_IN_MONO,
    AudioFormat.ENCODING_PCM_16BIT,
    maxOf(minBufferBytes, SAMPLE_RATE_HZ * 200 / 1000 * 2)
)
```

Bundle the Vosk model under Android assets only when the app actually needs offline voice commands; it is too large for a hello-world starter.
