# Vosk Voice Commands

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

Feed the recognizer 16 kHz mono PCM:

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

Bundle the Vosk model under Android assets when the app actually needs offline voice commands.
