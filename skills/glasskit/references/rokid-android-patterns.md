# Rokid Android Patterns

Use this when implementing the Android side of a Rokid Glasses app: HUD, touchpad keys, camera, local voice commands, speaker feedback, and lifecycle cleanup.

## HUD Constraints

- Rokid HUD target: 480x640 physical pixels, 240 dpi, portrait 3:4.
- Use black backgrounds and white foreground UI. Do not encode state by color alone.
- Keep text large, short, and stable. The HUD is not a phone screen.
- Use a fixed 3:4 viewport wrapper for phone/emulator previews so layout problems are visible before device testing.

Minimal viewport constants:

```kotlin
private const val HUD_REFERENCE_WIDTH_PX = 480f
private const val HUD_REFERENCE_HEIGHT_PX = 640f
private const val HUD_REFERENCE_DENSITY_DPI = 240f
private const val HUD_ASPECT_RATIO = HUD_REFERENCE_WIDTH_PX / HUD_REFERENCE_HEIGHT_PX
```

The starter asset includes `RokidHudViewportLayout`; copy that class into apps that need consistent phone/emulator rendering.

## Touchpad And Keys

Use `KEYCODE_ENTER` for the Rokid tap/select action. Use Android's back dispatcher as the source of truth for Back, then bridge Rokid's physical `KEYCODE_BACK` event into that dispatcher when the device sends it.

For apps with in-app navigation, the back handler should consume Back only away from the root/home screen. On the root/home screen, disable the callback and delegate to the system so Back exits the app.

```kotlin
private val backCallback = object : OnBackPressedCallback(false) {
    override fun handleOnBackPressed() {
        navigateBackWithinApp()
        updateBackCallback()
    }
}

override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    onBackPressedDispatcher.addCallback(this, backCallback)
    updateBackCallback()
}

private fun updateBackCallback() {
    backCallback.isEnabled = !isAtRootScreen()
}

@SuppressLint("GestureBackNavigation")
override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
    return when (keyCode) {
        KeyEvent.KEYCODE_ENTER -> {
            handleSelect()
            true
        }
        KeyEvent.KEYCODE_BACK -> {
            onBackPressedDispatcher.onBackPressed()
            true
        }
        KeyEvent.KEYCODE_DPAD_DOWN -> {
            handleNext()
            true
        }
        KeyEvent.KEYCODE_DPAD_UP -> {
            handlePrevious()
            true
        }
        else -> super.onKeyUp(keyCode, event)
    }
}
```

This pattern requires AndroidX `OnBackPressedCallback` through `ComponentActivity` or `AppCompatActivity`.

The `@SuppressLint("GestureBackNavigation")` annotation is intentional for the physical Rokid key bridge. Do not put app navigation logic directly in the `KEYCODE_BACK` branch; keep that logic in the back dispatcher callback so Android system Back, phone/emulator Back, and Rokid Back follow the same root-vs-inner-screen rules.

Do not use `KEYCODE_DPAD_CENTER` for tap/select. Existing swipe patterns map `KEYCODE_DPAD_DOWN` and `KEYCODE_DPAD_UP` to next/previous style navigation; verify direction against the app's intended gesture language.

For phone fallback testing, a single tap can call select, double tap can call back, and horizontal fling can call next/previous.

## Permissions And Lifecycle

- Request only the permissions needed by the current app: camera, microphone, or none.
- Add `FLAG_KEEP_SCREEN_ON` while the HUD is active.
- Stop CameraX, WebRTC, Vosk, `AudioRecord`, WebSockets, and backend sessions in `onStop` or `onDestroy`.
- Keep root-screen back available by delegating to Android's system Back behavior. Use in-app Back only for inner screens.

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

## Speaker Feedback

For simple audible feedback:

```kotlin
val tone = ToneGenerator(AudioManager.STREAM_MUSIC, 100)
tone.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
```

Release `ToneGenerator` in the host lifecycle.
