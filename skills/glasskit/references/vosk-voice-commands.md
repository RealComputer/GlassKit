# Vosk Voice Commands

Use Vosk for offline, fixed-phrase commands that mirror the Rokid touchpad actions: `select`, `back`, `next`, `previous`.

## Build inputs

```kotlin
// app/build.gradle.kts
defaultConfig {
    ndk {
        abiFilters += listOf("arm64-v8a", "x86_64")
    }
}

dependencies {
    implementation("com.alphacephei:vosk-android:0.3.75@aar")
    implementation("net.java.dev.jna:jna:5.18.1@aar")
}
```

Add `android.permission.RECORD_AUDIO` to the manifest and request it at runtime before opening `AudioRecord`.

Bundle a model at `app/src/main/assets/model-en-us/`. Recommended default: `vosk-model-small-en-us-0.15`.

```sh
ASSET_DIR=app/src/main/assets
curl -L -o /tmp/vosk-model-small-en-us-0.15.zip \
  https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip -q /tmp/vosk-model-small-en-us-0.15.zip -d /tmp
rm -rf "$ASSET_DIR/model-en-us"
mkdir -p "$ASSET_DIR"
mv /tmp/vosk-model-small-en-us-0.15 "$ASSET_DIR/model-en-us"
printf 'en-us-small-0.15-v1\n' > "$ASSET_DIR/model-en-us/uuid"
```

Load the bundled model through Vosk's Android storage helper:

```kotlin
StorageService.unpack(
    context.applicationContext,
    "model-en-us",
    "model",
    { model -> /* create Recognizer */ },
    { exception -> /* report init failure */ }
)
```

Check `context.assets.list("model-en-us")` before unpacking so missing-model builds fail with a useful message.

## Recognizer

```kotlin
private const val SAMPLE_RATE_HZ = 16_000

val commands = linkedSetOf("select", "back", "next", "previous")
val grammarJson = JSONArray().apply {
    commands.forEach { put(it) }
    put("[unk]")
}.toString()

val recognizer = Recognizer(model, SAMPLE_RATE_HZ.toFloat(), grammarJson).apply {
    setWords(false)
    setPartialWords(false)
    setEndpointerDelays(5.0f, 0.25f, 3.0f)
}
```

Normalize configured commands and recognized text with `trim().lowercase(Locale.US)`. Keep `[unk]` in the grammar so out-of-grammar speech does not force a command.

The endpoint delays above bias command recognition toward short utterances: tolerate startup silence, finalize quickly after trailing silence, and cap utterances at three seconds.

## Audio loop

Feed the recognizer 16 kHz mono PCM16 from a worker thread. Use sample counts, not byte counts, when passing a `ShortArray` to `acceptWaveForm`.

```kotlin
val minBufferBytes = AudioRecord.getMinBufferSize(
    SAMPLE_RATE_HZ,
    AudioFormat.CHANNEL_IN_MONO,
    AudioFormat.ENCODING_PCM_16BIT
)
require(minBufferBytes > 0)

val record = AudioRecord(
    MediaRecorder.AudioSource.MIC,
    SAMPLE_RATE_HZ,
    AudioFormat.CHANNEL_IN_MONO,
    AudioFormat.ENCODING_PCM_16BIT,
    maxOf(minBufferBytes, SAMPLE_RATE_HZ * 200 / 1000 * 2)
)

check(record.state == AudioRecord.STATE_INITIALIZED)
record.startRecording()
check(record.recordingState == AudioRecord.RECORDSTATE_RECORDING)

Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
val buffer = ShortArray(SAMPLE_RATE_HZ * 50 / 1000)

while (!stopRequested) {
    val readCount = record.read(buffer, 0, buffer.size)
    if (readCount <= 0) continue

    if (recognizer.acceptWaveForm(buffer, readCount)) {
        dispatchResult(recognizer.getResult())
    } else {
        publishPartial(recognizer.getPartialResult())
    }
}

dispatchResult(recognizer.getFinalResult())
```

Parse Vosk JSON with `JSONObject`: final results use `"text"` and partial results use `"partial"`.

```kotlin
val text = JSONObject(resultJson)
    .optString("text", "")
    .trim()
    .lowercase(Locale.US)

if (text in commands) {
    onCommand(text)
}
```

Callbacks from the recognition thread must hop to the main thread before touching Android views.

## Lifecycle

- Start only after the model is unpacked and `RECORD_AUDIO` is granted.
- On stop, set a stop flag, stop `AudioRecord`, interrupt/join the worker briefly, release `AudioRecord`, clear partial UI state, and reset any audio meter to zero.
- On destroy, close `Recognizer` and `Model`.
- Call `recognizer.reset()` before each new listening session.
- Suppress duplicate final commands in a short window, around `400ms`, because endpointing can produce repeated finals.
