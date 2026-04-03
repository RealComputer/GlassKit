package com.example.rokidfeaturedemo

import android.annotation.SuppressLint
import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Process
import android.os.SystemClock
import android.util.Log
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.StorageService
import java.util.LinkedHashSet
import java.util.Locale

class VoiceCommandRecognizer(
    context: Context,
    commands: Collection<String>,
    private val onResult: (String) -> Unit,
    private val onPartialText: (String) -> Unit = {},
    private val onAudioLevel: (Int) -> Unit = {},
    private val onStatus: (String) -> Unit = {},
    private val onErrorText: (String) -> Unit = {}
) {

    companion object {
        private const val TAG = "RokidFeatureDemoVoice"
        private const val SAMPLE_RATE_HZ = 16_000
        private const val DUPLICATE_WINDOW_MS = 400L
        private const val AUDIO_LEVEL_INTERVAL_MS = 150L
        private const val MIN_BUFFER_DURATION_MS = 200
        private const val AUDIO_READ_CHUNK_MS = 50
        private const val ENDPOINTER_INITIAL_SILENCE_SECONDS = 5.0f
        private const val ENDPOINTER_TRAILING_SILENCE_SECONDS = 0.25f
        private const val ENDPOINTER_MAX_UTTERANCE_SECONDS = 3.0f
    }

    private val appContext = context.applicationContext
    private val normalizedCommands = LinkedHashSet<String>().apply {
        commands.forEach { add(it.trim().lowercase(Locale.US)) }
    }
    private val grammarJson = JSONArray().apply {
        normalizedCommands.forEach { put(it) }
        put("[unk]")
    }.toString()

    private var ready = false
    private var initializing = false
    private var pendingStart = false
    private var model: Model? = null
    private var recognizer: Recognizer? = null
    private var audioRecord: AudioRecord? = null
    private var workerThread: Thread? = null

    @Volatile
    private var stopRequested = false

    private var lastCommand = ""
    private var lastCommandAtMs = 0L
    private var lastPartialText = ""
    private var lastAudioLevelAtMs = 0L

    fun start() {
        pendingStart = true
        ensureInitialized()
    }

    fun stop() {
        pendingStart = false
        stopRequested = true

        audioRecord?.let { record ->
            runCatching {
                if (record.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                    record.stop()
                }
            }
        }

        workerThread?.let { thread ->
            thread.interrupt()
            runCatching { thread.join(1_000) }
        }

        workerThread = null
        audioRecord?.release()
        audioRecord = null
        onAudioLevel(0)
        publishPartial("")
    }

    fun release() {
        stop()
        recognizer?.close()
        recognizer = null
        model?.close()
        model = null
        ready = false
        initializing = false
    }

    private fun ensureInitialized() {
        if (ready) {
            startInternal()
            return
        }
        if (initializing) return
        if (!hasBundledModel()) {
            pendingStart = false
            onErrorText("Voice model missing. Run ./scripts/download_vosk_model.sh before building.")
            return
        }

        initializing = true
        onStatus("Loading voice model...")
        StorageService.unpack(
            appContext,
            "model-en-us",
            "model",
            { loadedModel ->
                try {
                    model = loadedModel
                    recognizer = Recognizer(loadedModel, SAMPLE_RATE_HZ.toFloat(), grammarJson).apply {
                        setWords(false)
                        setPartialWords(false)
                        // The command grammar is tiny, so bias endpointing toward faster finalization.
                        setEndpointerDelays(
                            ENDPOINTER_INITIAL_SILENCE_SECONDS,
                            ENDPOINTER_TRAILING_SILENCE_SECONDS,
                            ENDPOINTER_MAX_UTTERANCE_SECONDS
                        )
                    }
                    ready = true
                    initializing = false
                    onStatus("Voice commands ready.")
                    if (pendingStart) {
                        startInternal()
                    }
                } catch (exception: Exception) {
                    initializing = false
                    onErrorText(
                        "Voice init failed: ${exception.message ?: exception.javaClass.simpleName}"
                    )
                }
            },
            { exception ->
                initializing = false
                onErrorText(
                    "Voice model unpack failed: ${exception.message ?: exception.javaClass.simpleName}"
                )
            }
        )
    }

    private fun hasBundledModel(): Boolean {
        return runCatching {
            val files = appContext.assets.list("model-en-us")
            files != null && files.isNotEmpty()
        }.getOrDefault(false)
    }

    private fun startInternal() {
        if (!ready || workerThread != null) return
        val permissionState = ContextCompat.checkSelfPermission(
            appContext,
            Manifest.permission.RECORD_AUDIO
        )
        if (permissionState != PackageManager.PERMISSION_GRANTED) {
            pendingStart = false
            onErrorText("Microphone permission missing.")
            return
        }

        val activeRecognizer = recognizer ?: return
        activeRecognizer.reset()
        publishPartial("")

        val minBufferBytes = AudioRecord.getMinBufferSize(
            SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBufferBytes <= 0) {
            onErrorText("Microphone init failed: invalid buffer size $minBufferBytes")
            return
        }

        try {
            @SuppressLint("MissingPermission")
            val record = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE_HZ,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minBufferBytes, SAMPLE_RATE_HZ * MIN_BUFFER_DURATION_MS / 1000 * 2)
            )
            if (record.state != AudioRecord.STATE_INITIALIZED) {
                record.release()
                onErrorText("Microphone init failed: AudioRecord state=${record.state}")
                return
            }

            record.startRecording()
            if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                record.release()
                onErrorText("Microphone start failed: recorder did not start.")
                return
            }

            stopRequested = false
            audioRecord = record
            workerThread = Thread(
                { runRecognitionLoop(record, activeRecognizer) },
                "rokid-feature-demo-vosk"
            ).apply { start() }
            onAudioLevel(0)
            onStatus("Listening for select, back, next, previous.")
        } catch (exception: Exception) {
            onErrorText(
                "Microphone start failed: ${exception.message ?: exception.javaClass.simpleName}"
            )
        }
    }

    private fun runRecognitionLoop(record: AudioRecord, activeRecognizer: Recognizer) {
        Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
        val buffer = ShortArray((SAMPLE_RATE_HZ * AUDIO_READ_CHUNK_MS / 1000).coerceAtLeast(1))

        try {
            while (!stopRequested && !Thread.currentThread().isInterrupted) {
                val readCount = record.read(buffer, 0, buffer.size)
                if (readCount < 0) {
                    if (!stopRequested) {
                        onErrorText("Microphone read failed: $readCount")
                    }
                    return
                }
                if (readCount == 0) continue

                publishAudioLevel(buffer, readCount)

                if (activeRecognizer.acceptWaveForm(buffer, readCount)) {
                    publishPartial("")
                    dispatchResult(activeRecognizer.getResult())
                } else {
                    publishPartial(partialFromHypothesis(activeRecognizer.getPartialResult()))
                }
            }

            if (!stopRequested) {
                publishPartial("")
                dispatchResult(activeRecognizer.getFinalResult())
            }
        } catch (exception: Exception) {
            if (!stopRequested) {
                onErrorText(
                    "Voice runtime error: ${exception.message ?: exception.javaClass.simpleName}"
                )
            }
        } finally {
            runCatching {
                if (record.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                    record.stop()
                }
            }
        }
    }

    private fun dispatchResult(hypothesis: String) {
        val text = resultFromHypothesis(hypothesis) ?: return
        val now = SystemClock.elapsedRealtime()
        if (text == lastCommand && now - lastCommandAtMs < DUPLICATE_WINDOW_MS) {
            return
        }

        lastCommand = text
        lastCommandAtMs = now

        if (normalizedCommands.contains(text)) {
            Log.d(TAG, "Recognized command: $text")
            onResult(text)
        }
    }

    private fun resultFromHypothesis(hypothesis: String): String? {
        if (hypothesis.isBlank()) return null

        val text = try {
            JSONObject(hypothesis)
                .optString("text", "")
                .trim()
                .lowercase(Locale.US)
        } catch (_: Exception) {
            return null
        }

        return text.ifEmpty { null }
    }

    private fun partialFromHypothesis(hypothesis: String): String {
        if (hypothesis.isBlank()) return ""

        return try {
            JSONObject(hypothesis)
                .optString("partial", "")
                .trim()
                .lowercase(Locale.US)
        } catch (_: Exception) {
            ""
        }
    }

    private fun publishPartial(text: String) {
        if (text == lastPartialText) return
        lastPartialText = text
        onPartialText(text)
    }

    private fun publishAudioLevel(buffer: ShortArray, readCount: Int) {
        val now = SystemClock.elapsedRealtime()
        if (now - lastAudioLevelAtMs < AUDIO_LEVEL_INTERVAL_MS) return

        var peak = 0
        for (index in 0 until readCount) {
            val amplitude = kotlin.math.abs(buffer[index].toInt())
            if (amplitude > peak) peak = amplitude
        }

        lastAudioLevelAtMs = now
        onAudioLevel((peak * 100 / Short.MAX_VALUE).coerceIn(0, 100))
    }
}
