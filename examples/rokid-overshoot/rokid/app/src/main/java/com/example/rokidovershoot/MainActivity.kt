package com.example.rokidovershoot

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.example.rokidovershoot.databinding.ActivityMainBinding
import org.webrtc.PeerConnection

class MainActivity : AppCompatActivity(), OvershootSessionClient.Listener {

    private lateinit var binding: ActivityMainBinding
    private var sessionClient: OvershootSessionClient? = null
    private var isRunning = false

    private val resultLines = ArrayDeque<String>()

    private val backendBaseUrl: String = BuildConfig.BACKEND_BASE_URL

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        binding.tvTitle.text = getString(R.string.app_name)
        setStatus("Checking camera...")
        renderResultLog()

        ensurePermissions()
    }

    override fun onDestroy() {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onDestroy()
        releaseSessionClientAsync()
    }

    override fun onStop() {
        stopStreaming()
        super.onStop()
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_ENTER -> {
                if (isRunning) {
                    stopStreaming()
                } else {
                    startStreaming()
                }
                true
            }

            else -> super.onKeyUp(keyCode, event)
        }
    }

    private fun ensurePermissions() {
        val needed = listOf(Manifest.permission.CAMERA).filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (needed.isEmpty()) {
            setStatus(STATUS_READY)
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
        if (requestCode != REQ_PERMISSIONS) return

        if (grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            setStatus(STATUS_READY)
        } else {
            setStatus("Camera permission required")
        }
    }

    private fun startStreaming() {
        if (sessionClient != null) return

        if (!hasPermissions()) {
            ensurePermissions()
            return
        }

        clearResultLog()
        isRunning = true
        setStatus(STATUS_STARTING)

        sessionClient = OvershootSessionClient(
            context = applicationContext,
            backendBaseUrl = backendBaseUrl,
            listener = this
        ).also { it.start() }
    }

    private fun stopStreaming() {
        isRunning = false
        val activeClient = sessionClient ?: run {
            setStatus(STATUS_STOPPED)
            return
        }

        setStatus(STATUS_STOPPING)
        sessionClient = null
        Thread { activeClient.release() }.start()
    }

    private fun releaseSessionClientAsync() {
        val activeClient = sessionClient ?: return
        sessionClient = null
        isRunning = false
        Thread { activeClient.release() }.start()
    }

    override fun onConnectionStateChanged(state: PeerConnection.IceConnectionState) {
        runOnUiThread {
            if (!isRunning) return@runOnUiThread

            val statusText = when (state) {
                PeerConnection.IceConnectionState.NEW,
                PeerConnection.IceConnectionState.CHECKING -> STATUS_STARTING

                PeerConnection.IceConnectionState.CONNECTED,
                PeerConnection.IceConnectionState.COMPLETED -> STATUS_LIVE

                PeerConnection.IceConnectionState.DISCONNECTED,
                PeerConnection.IceConnectionState.FAILED -> "Connection lost"

                PeerConnection.IceConnectionState.CLOSED -> STATUS_STOPPED
            }
            setStatus(statusText)
        }
    }

    override fun onResultText(text: String) {
        runOnUiThread {
            appendResultText(text)
        }
    }

    override fun onStatus(message: String) {
        runOnUiThread {
            if (!isRunning) return@runOnUiThread

            val normalizedMessage = message.lowercase()
            val statusText = if (
                "streaming" in normalizedMessage ||
                "receiving results" in normalizedMessage
            ) {
                STATUS_LIVE
            } else {
                STATUS_STARTING
            }
            setStatus(statusText)
        }
    }

    override fun onError(message: String, throwable: Throwable?) {
        runOnUiThread {
            setStatus("Connection issue. Tap temple to retry")
        }
    }

    override fun onSessionStopped() {
        runOnUiThread {
            isRunning = false
            setStatus(STATUS_STOPPED)
        }
    }

    private fun appendResultText(text: String) {
        val normalizedLines = text
            .lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .toList()

        if (normalizedLines.isEmpty()) {
            return
        }

        val messageBlock = normalizedLines.joinToString("\n")
        resultLines.addLast(messageBlock)
        while (resultLines.size > MAX_RESULT_LINES) {
            resultLines.removeFirst()
        }

        renderResultLog()
    }

    private fun clearResultLog() {
        resultLines.clear()
        renderResultLog()
    }

    private fun renderResultLog() {
        binding.tvLog.text = if (resultLines.isEmpty()) {
            ""
        } else {
            resultLines.joinToString("\n\n")
        }

        binding.svLog.post {
            binding.svLog.fullScroll(View.FOCUS_DOWN)
        }
    }

    private fun setStatus(text: String) {
        binding.tvStatus.text = text
    }

    companion object {
        private const val REQ_PERMISSIONS = 1001
        private const val MAX_RESULT_LINES = 180
        private const val STATUS_READY = "Tap temple to start"
        private const val STATUS_STARTING = "Starting..."
        private const val STATUS_LIVE = "Live"
        private const val STATUS_STOPPING = "Stopping..."
        private const val STATUS_STOPPED = "Stopped. Tap temple to start"
    }
}
