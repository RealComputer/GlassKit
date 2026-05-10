# Rokid Inputs

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

Use CameraX and bind the rear camera. The practical Rokid Glasses capture floor is 1024x768 at 15 fps; request `1024x768`, not `768x1024`, then set target rotation so CameraX applies the correct transform.

Rokid Glasses expose only the rear/outward camera. Configure CameraX at the Application level to expose only `CameraSelector.DEFAULT_BACK_CAMERA` before any `ProcessCameraProvider` is initialized. This avoids CameraX front-camera validation retries on hardware that reports no front camera, and still works for Rokid-style phone/emulator testing with a back camera. Omit this only if the same app process needs front-camera features.

```kotlin
import android.app.Application
import androidx.camera.camera2.Camera2Config
import androidx.camera.core.CameraSelector
import androidx.camera.core.CameraXConfig

class RokidApplication : Application(), CameraXConfig.Provider {
    override fun getCameraXConfig(): CameraXConfig {
        return CameraXConfig.Builder.fromConfig(Camera2Config.defaultConfig())
            .setAvailableCamerasLimiter(CameraSelector.DEFAULT_BACK_CAMERA)
            .build()
    }
}
```

Register the Application in `AndroidManifest.xml`:

```xml
<application
    android:name=".RokidApplication"
    ...>
```

If the app already has a custom `Application`, implement `CameraXConfig.Provider` there instead of adding another Application class.

```kotlin
private val rokidCameraSize = Size(1024, 768)
private val rokidCameraFps = Range(15, 15)

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

Do not rely on Camera2 accepting sub-15 fps requests on Rokid; for lower outbound rates, capture at a supported mode and throttle downstream processing or WebRTC output.

## Microphone Access

Use the standard Android microphone stack. The Rokid-specific choices are `MediaRecorder.AudioSource.MIC` and mono capture.

For direct PCM access, use `AudioRecord`:

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

For WebRTC or another streaming stack that owns capture, configure that stack to use the same Rokid-friendly microphone path:

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
