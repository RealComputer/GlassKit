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

## Microphone Access

Use the standard Android microphone stack; Rokid Glasses do not need a separate microphone SDK. The Rokid-specific choices are `MediaRecorder.AudioSource.MIC`, mono capture, and 16 kHz input when the capture stack lets the app choose the sample rate.

For direct PCM access, use `AudioRecord` with 16 kHz mono PCM 16-bit:

```kotlin
private const val ROKID_MIC_SAMPLE_RATE_HZ = 16_000
private const val ROKID_MIC_BUFFER_MS = 200

val minBufferBytes = AudioRecord.getMinBufferSize(
    ROKID_MIC_SAMPLE_RATE_HZ,
    AudioFormat.CHANNEL_IN_MONO,
    AudioFormat.ENCODING_PCM_16BIT
)
require(minBufferBytes > 0) { "Invalid microphone buffer size: $minBufferBytes" }

val record = AudioRecord(
    MediaRecorder.AudioSource.MIC,
    ROKID_MIC_SAMPLE_RATE_HZ,
    AudioFormat.CHANNEL_IN_MONO,
    AudioFormat.ENCODING_PCM_16BIT,
    maxOf(minBufferBytes, ROKID_MIC_SAMPLE_RATE_HZ * ROKID_MIC_BUFFER_MS / 1000 * 2)
)

if (record.state != AudioRecord.STATE_INITIALIZED) {
    record.release()
    error("Microphone failed to initialize: state=${record.state}")
}

record.startRecording()
if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
    record.release()
    error("Microphone did not start recording")
}
```

Run `AudioRecord.read(...)` on a background thread with `Process.THREAD_PRIORITY_AUDIO`, then stop and release the recorder when capture ends.

For WebRTC or another streaming stack that owns capture, configure that stack to use the same Rokid-friendly microphone path instead of adding a separate `AudioRecord` loop:

```kotlin
JavaAudioDeviceModule.builder(context)
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
    .createAudioDeviceModule().apply {
        setMicrophoneMute(false)
        setSpeakerMute(false)
    }
```

For simultaneous mic capture and speaker playback, use `USAGE_MEDIA` instead of a voice-call route and disable hardware AEC/noise suppression to avoid the vendor VOIP path. Request normal Android `RECORD_AUDIO` permission before starting either path.

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
