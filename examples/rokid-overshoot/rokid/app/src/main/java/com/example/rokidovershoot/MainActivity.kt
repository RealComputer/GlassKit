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

    private val visionSessionUrl: String = BuildConfig.VISION_SESSION_URL

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        binding.tvTitle.text = getString(R.string.app_name)
        setStatus("Requesting camera permission...")
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
            setStatus("Press ENTER to start")
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
            setStatus("Press ENTER to start")
        } else {
            setStatus("Camera permission denied")
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
        setStatus("Starting stream... (ENTER to stop)")

        sessionClient = OvershootSessionClient(
            context = applicationContext,
            sessionUrl = visionSessionUrl,
            listener = this
        ).also { it.start() }
    }

    private fun stopStreaming() {
        isRunning = false
        val activeClient = sessionClient ?: run {
            setStatus("Stopped. Press ENTER to start")
            return
        }

        setStatus("Stopping stream...")
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

            val readable = state.name.lowercase().replace('_', ' ')
            setStatus("Connection: $readable (ENTER to stop)")
        }
    }

    override fun onResultText(text: String) {
        runOnUiThread {
            appendResultText(text)
        }
    }

    override fun onStatus(message: String) {
        runOnUiThread {
            if (isRunning) {
                setStatus("$message (ENTER to stop)")
            } else {
                setStatus("$message")
            }
        }
    }

    override fun onError(message: String, throwable: Throwable?) {
        runOnUiThread {
            setStatus("Error: $message")
        }
    }

    override fun onSessionStopped() {
        runOnUiThread {
            isRunning = false
            setStatus("Stopped. Press ENTER to start")
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

        for (line in normalizedLines) {
            resultLines.addLast(line)
            while (resultLines.size > MAX_RESULT_LINES) {
                resultLines.removeFirst()
            }
        }

        renderResultLog()
    }

    private fun clearResultLog() {
        resultLines.clear()
        renderResultLog()
    }

    private fun renderResultLog() {
        binding.tvLog.text = if (resultLines.isEmpty()) {
            "Waiting for results..."
        } else {
            resultLines.joinToString("\n")
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
    }
}
