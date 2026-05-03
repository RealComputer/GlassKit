# Rokid Android Patterns

## Touchpad

Rokid Glasses touchpad gestures come through Android input handling.

| Rokid touchpad action | Android handling | Typical app action |
| --- | --- | --- |
| Tap | `KeyEvent.KEYCODE_ENTER` | Select / confirm |
| Double-tap | `OnBackPressedCallback` | Back / cancel |
| Swipe forward | `KeyEvent.KEYCODE_DPAD_DOWN` | Next / move focus forward |
| Swipe backward | `KeyEvent.KEYCODE_DPAD_UP` | Previous / move focus backward |

For actual implementation example and optional phone/emulator touch fallback, `../assets/rokid-hello-world/`.

## Camera Access

Use CameraX and bind the rear camera. The confirmed Rokid Glasses camera request is 1024x768 at 5 fps. The gotcha is that the requested CameraX size is landscape-shaped even though the camera image should appear portrait; request `1024x768`, not `768x1024`, then set target rotation so CameraX applies the correct transform.

```kotlin
private val rokidCameraSize = Size(1024, 768)
private val rokidCameraFps = Range(5, 5)

@OptIn(ExperimentalCamera2Interop::class)
private fun bindRokidCamera(
    lifecycleOwner: LifecycleOwner,
    cameraProvider: ProcessCameraProvider,
    previewView: PreviewView
) {
    previewView.implementationMode = PreviewView.ImplementationMode.COMPATIBLE
    previewView.scaleType = PreviewView.ScaleType.FIT_CENTER

    val previewBuilder = Preview.Builder()
        .setTargetRotation(previewView.display?.rotation ?: Surface.ROTATION_0)
        .setResolutionSelector(
            ResolutionSelector.Builder()
                .setResolutionStrategy(
                    ResolutionStrategy(
                        rokidCameraSize,
                        ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER
                    )
                )
                .build()
        )

    Camera2Interop.Extender(previewBuilder).setCaptureRequestOption(
        CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,
        rokidCameraFps
    )

    val preview = previewBuilder.build().also {
        it.setSurfaceProvider(previewView.surfaceProvider)
    }

    cameraProvider.unbindAll()
    cameraProvider.bindToLifecycle(
        lifecycleOwner,
        CameraSelector.DEFAULT_BACK_CAMERA,
        preview
    )
}
```

Request normal Android `CAMERA` permission before binding, and unbind the provider when the camera screen is no longer visible.

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
