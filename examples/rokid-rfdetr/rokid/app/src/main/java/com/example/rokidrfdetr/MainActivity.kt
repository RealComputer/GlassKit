package com.example.rokidrfdetr

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.StyleSpan
import android.text.style.StrikethroughSpan
import android.view.KeyEvent
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.example.rokidrfdetr.databinding.ActivityMainBinding
import org.webrtc.PeerConnection
import java.util.Locale
class MainActivity : AppCompatActivity(), BackendVisionClient.Listener {

    private lateinit var binding: ActivityMainBinding

    private var visionClient: BackendVisionClient? = null

    private var speedrunConfig: SpeedrunConfig? = null
    private var speedrunState = SpeedrunState(RunState.IDLE, 0, 0)
    private var splitTimes: MutableList<Long?> = mutableListOf()
    private var lastCompletedCount = 0

    private var runStarted = false
    private var timerRunning = false
    private var timerStartMs = 0L
    private var finalElapsedMs = 0L

    private val timerHandler = Handler(Looper.getMainLooper())
    private val reconnectHandler = Handler(Looper.getMainLooper())
    private val timerRunnable = object : Runnable {
        override fun run() {
            updateTimer()
            if (timerRunning) {
                timerHandler.postDelayed(this, 100L)
            }
        }
    }

    companion object {
        private const val REQ_PERMISSIONS = 1001
        private const val LABEL_PAD = 28
        private const val TIME_PLACEHOLDER = "--:--.--"
    }

    private val visionSessionUrl: String = BuildConfig.VISION_SESSION_URL

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        setStatus("Requesting camera permission...")
        binding.tvTitle.text = "Loading speedrun..."
        binding.tvTimer.text = formatElapsed(0L)
        binding.tvSplits.text = "Waiting for config..."

        ensurePermissions()
    }

    private fun ensurePermissions() {
        val needed = listOf(Manifest.permission.CAMERA).filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (needed.isEmpty()) {
            startVisionIfNeeded()
        } else {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), REQ_PERMISSIONS)
        }
    }

    private fun hasPermissions(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.CAMERA
        ) == PackageManager.PERMISSION_GRANTED
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_PERMISSIONS) {
            if (grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
                startVisionIfNeeded()
            } else {
                setStatus("Camera permission denied; streaming unavailable.")
            }
        }
    }

    override fun onDestroy() {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onDestroy()
        releaseVisionClientAsync()
        stopTimer()
        reconnectHandler.removeCallbacksAndMessages(null)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_ENTER -> {
                startRunIfNeeded()
                true
            }

            KeyEvent.KEYCODE_DPAD_UP -> {
                visionClient?.sendDebugStep("next")
                true
            }

            KeyEvent.KEYCODE_DPAD_DOWN -> {
                visionClient?.sendDebugStep("prev")
                true
            }

            else -> super.onKeyUp(keyCode, event)
        }
    }

    private fun startVisionIfNeeded() {
        if (visionClient != null) return
        if (!hasPermissions()) {
            ensurePermissions()
            return
        }

        setStatus("Connecting...")
        visionClient = BackendVisionClient(
            context = applicationContext,
            sessionUrl = visionSessionUrl,
            listener = this
        ).also { it.start() }
    }

    private fun startRunIfNeeded() {
        if (runStarted) return
        runStarted = true
        finalElapsedMs = 0L
        startTimer()
        visionClient?.sendRunStart()
        renderSplits()
    }

    private fun startTimer() {
        if (timerRunning) return
        timerStartMs = SystemClock.elapsedRealtime()
        timerRunning = true
        updateTimer()
        timerHandler.postDelayed(timerRunnable, 100L)
    }

    private fun stopTimer() {
        timerRunning = false
        timerHandler.removeCallbacks(timerRunnable)
    }

    private fun updateTimer() {
        val elapsed = if (timerRunning) {
            SystemClock.elapsedRealtime() - timerStartMs
        } else {
            finalElapsedMs
        }
        binding.tvTimer.text = formatElapsed(elapsed)
    }

    private fun currentElapsedMs(): Long {
        return if (timerRunning) {
            SystemClock.elapsedRealtime() - timerStartMs
        } else {
            finalElapsedMs
        }
    }

    private fun formatElapsed(ms: Long): String {
        val totalSeconds = ms / 1000
        val minutes = totalSeconds / 60
        val seconds = totalSeconds % 60
        val centis = (ms % 1000) / 10
        return String.format(Locale.US, "%02d:%02d.%02d", minutes, seconds, centis)
    }

    private fun setStatus(text: String) {
        binding.tvStatus.text = text
    }

    override fun onConnectionStateChanged(state: PeerConnection.IceConnectionState) {
        runOnUiThread {
            if (state == PeerConnection.IceConnectionState.CONNECTED ||
                state == PeerConnection.IceConnectionState.COMPLETED
            ) {
                setStatus("")
            } else {
                setStatus("Connection: $state")
            }
            if (state == PeerConnection.IceConnectionState.FAILED ||
                state == PeerConnection.IceConnectionState.CLOSED ||
                state == PeerConnection.IceConnectionState.DISCONNECTED
            ) {
                releaseVisionClientAsync()
                setStatus("Connection: $state (reconnecting)")
                reconnectHandler.removeCallbacksAndMessages(null)
                reconnectHandler.postDelayed(
                    { if (!isFinishing && !isDestroyed) startVisionIfNeeded() },
                    1000L
                )
            }
        }
    }

    override fun onError(message: String, throwable: Throwable?) {
        runOnUiThread {
            setStatus("Error: $message")
        }
    }

    override fun onConfig(config: SpeedrunConfig) {
        runOnUiThread {
            speedrunConfig = config
            binding.tvTitle.text = config.name
            splitTimes = MutableList(config.totalSplits) { null }
            lastCompletedCount = 0
            renderSplits()
        }
    }

    override fun onStateUpdate(state: SpeedrunState) {
        runOnUiThread {
            applyState(state)
            renderSplits()
        }
    }

    override fun onSplitCompleted(splitIndex: Int, state: SpeedrunState) {
        runOnUiThread {
            applyState(state)
            recordSplitTime(splitIndex)
            renderSplits()
        }
    }

    private fun applyState(state: SpeedrunState) {
        speedrunState = state
        if (state.completedCount < lastCompletedCount) {
            for (i in state.completedCount until splitTimes.size) {
                splitTimes[i] = null
            }
        }
        lastCompletedCount = state.completedCount
        if (state.runState == RunState.FINISHED) {
            if (timerRunning) {
                finalElapsedMs = currentElapsedMs()
                stopTimer()
                updateTimer()
            }
        }
    }

    private fun recordSplitTime(splitIndex: Int) {
        if (splitIndex < 0 || splitIndex >= splitTimes.size) return
        if (!runStarted) return
        splitTimes[splitIndex] = currentElapsedMs()
    }

    private fun releaseVisionClientAsync() {
        val client = visionClient ?: return
        visionClient = null
        Thread { client.release() }.start()
    }

    private fun renderSplits() {
        val config = speedrunConfig
        if (config == null) {
            binding.tvSplits.text = "Waiting for config..."
            return
        }

        val labelWidth = computeLabelWidth()
        val builder = SpannableStringBuilder()
        var flatIndex = 0

        for (group in config.groups) {
            if (builder.isNotEmpty()) builder.append("\n")
            val groupStart = builder.length
            builder.append(group.name)
            val groupEnd = builder.length
            builder.setSpan(
                StyleSpan(Typeface.BOLD),
                groupStart,
                groupEnd,
                Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
            )
            builder.append("\n")

            for (split in group.splits) {
                val isActive = speedrunState.runState != RunState.FINISHED &&
                    flatIndex == speedrunState.activeIndex
                val isComplete = flatIndex < speedrunState.completedCount

                val prefix = if (isActive) "> " else "  "
                val label = split.label.take(labelWidth).padEnd(labelWidth)
                val timeText = splitTimes.getOrNull(flatIndex)?.let { formatElapsed(it) }
                    ?: TIME_PLACEHOLDER

                val labelStart = builder.length
                builder.append(prefix)
                builder.append(label)
                val labelEnd = builder.length
                builder.append("  ")
                builder.append(timeText)

                if (isActive) {
                    builder.setSpan(
                        StyleSpan(Typeface.BOLD_ITALIC),
                        labelStart,
                        labelEnd,
                        Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
                    )
                } else if (isComplete) {
                    builder.setSpan(
                        StrikethroughSpan(),
                        labelStart,
                        labelEnd,
                        Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
                    )
                }

                builder.append("\n")
                flatIndex += 1
            }
        }

        if (builder.isNotEmpty() && builder.last() == '\n') {
            builder.delete(builder.length - 1, builder.length)
        }
        binding.tvSplits.text = builder
    }

    private fun computeLabelWidth(): Int {
        val widthPx = binding.tvSplits.width
        if (widthPx <= 0) return LABEL_PAD
        val charWidth = binding.tvSplits.paint.measureText("0")
        if (charWidth <= 0f) return LABEL_PAD
        val totalCols = (widthPx / charWidth).toInt()
        val reserved = 2 + 2 + TIME_PLACEHOLDER.length
        val available = totalCols - reserved
        return available.coerceAtLeast(1)
    }
}
