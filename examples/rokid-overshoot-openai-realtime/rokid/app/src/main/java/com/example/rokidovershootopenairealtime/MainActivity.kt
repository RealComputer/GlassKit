package com.example.rokidovershootopenairealtime

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Bundle
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.StrikethroughSpan
import android.text.style.StyleSpan
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.example.rokidovershootopenairealtime.BackendControlClient.HudState
import com.example.rokidovershootopenairealtime.BackendControlClient.HudTask
import com.example.rokidovershootopenairealtime.databinding.ActivityMainBinding
import org.webrtc.PeerConnection

class MainActivity : AppCompatActivity(), BackendControlClient.Listener {

    private lateinit var binding: ActivityMainBinding

    private var controlClient: BackendControlClient? = null
    private var overshootClient: OvershootSessionClient? = null
    private var realtimeClient: OpenAIRealtimeClient? = null

    private var currentSessionId: String? = null
    private var currentHudState: HudState? = null
    private var currentTranscript = ""
    private var currentSpeechEpoch = 0
    private var pendingStart = false
    private var isRunning = false
    private var idleMessage = ""
    private var mediaClientGeneration = 0

    private val backendBaseUrl: String = BuildConfig.BACKEND_BASE_URL

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        binding.tvTitle.text = getString(R.string.app_name)
        renderIdleState(getString(R.string.connecting_backend))
        ensurePermissions()
    }

    override fun onStart() {
        super.onStart()
        if (hasPermissions()) {
            connectControlIfNeeded()
            if (currentSessionId == null) {
                renderIdleState(getString(R.string.connecting_backend))
            }
        }
    }

    override fun onDestroy() {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        stopMediaClients()
        disconnectControl()
        super.onDestroy()
    }

    override fun onStop() {
        stopWorkflow()
        disconnectControl()
        super.onStop()
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_ENTER -> {
                if (isRunning) {
                    stopWorkflow()
                } else {
                    startWorkflow()
                }
                true
            }

            KeyEvent.KEYCODE_DPAD_UP -> {
                if (isRunning) {
                    controlClient?.sendDebugStep("forward")
                }
                true
            }

            KeyEvent.KEYCODE_DPAD_DOWN -> {
                if (isRunning) {
                    controlClient?.sendDebugStep("backward")
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
            connectControlIfNeeded()
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
            connectControlIfNeeded()
            if (pendingStart) {
                startWorkflow()
            }
        } else {
            renderIdleState("Camera permission required")
        }
    }

    private fun connectControlIfNeeded() {
        val existing = controlClient
        if (existing != null) {
            existing.connect()
            return
        }

        controlClient = BackendControlClient(
            backendBaseUrl = backendBaseUrl,
            listener = this
        ).also { it.connect() }
    }

    private fun startWorkflow() {
        if (!hasPermissions()) {
            pendingStart = true
            ensurePermissions()
            return
        }

        connectControlIfNeeded()
        val sessionId = currentSessionId
        if (sessionId.isNullOrBlank()) {
            pendingStart = true
            renderIdleState(getString(R.string.connecting_backend))
            return
        }
        if (isRunning) return

        pendingStart = false
        isRunning = true
        controlClient?.sendStart()
        startMediaClients(sessionId)
    }

    private fun stopWorkflow() {
        pendingStart = false
        if (!isRunning) return
        isRunning = false
        controlClient?.sendStop()
        stopMediaClients()
    }

    private fun startMediaClients(sessionId: String) {
        stopMediaClients()
        mediaClientGeneration += 1
        val generation = mediaClientGeneration

        overshootClient = OvershootSessionClient(
            context = applicationContext,
            backendBaseUrl = backendBaseUrl,
            sessionId = sessionId,
            listener = object : OvershootSessionClient.Listener {
                override fun onConnectionStateChanged(state: PeerConnection.IceConnectionState) {
                    runOnUiThread {
                        if (generation != mediaClientGeneration || !isRunning) return@runOnUiThread
                        if (state == PeerConnection.IceConnectionState.FAILED) {
                            showHint("Video link: $state")
                        }
                    }
                }

                override fun onError(message: String, throwable: Throwable?) {
                    runOnUiThread {
                        if (generation != mediaClientGeneration || !isRunning) return@runOnUiThread
                        showHint("Video error: $message")
                    }
                }
            }
        ).also { it.start() }

        realtimeClient = OpenAIRealtimeClient(
            context = applicationContext,
            backendBaseUrl = backendBaseUrl,
            sessionId = sessionId,
            listener = object : OpenAIRealtimeClient.Listener {
                override fun onTranscriptDelta(itemId: String, delta: String) {
                    runOnUiThread {
                        if (generation != mediaClientGeneration) return@runOnUiThread
                        currentTranscript += delta
                        renderTranscript()
                    }
                }

                override fun onTranscriptDone(itemId: String, transcript: String) {
                    runOnUiThread {
                        if (generation != mediaClientGeneration) return@runOnUiThread
                        currentTranscript = transcript
                        renderTranscript()
                    }
                }

                override fun onConnectionStateChanged(state: PeerConnection.IceConnectionState) {
                    runOnUiThread {
                        if (generation != mediaClientGeneration || !isRunning) return@runOnUiThread
                        if (state == PeerConnection.IceConnectionState.FAILED) {
                            showHint("Audio link: $state")
                        }
                    }
                }

                override fun onError(message: String, throwable: Throwable?) {
                    runOnUiThread {
                        if (generation != mediaClientGeneration || !isRunning) return@runOnUiThread
                        showHint("Audio error: $message")
                    }
                }
            }
        ).also {
            it.setSpeechEpoch(currentSpeechEpoch)
            it.start()
        }
    }

    private fun stopMediaClients() {
        mediaClientGeneration += 1
        val activeOvershoot = overshootClient
        overshootClient = null
        if (activeOvershoot != null) {
            Thread { activeOvershoot.release() }.start()
        }

        val activeRealtime = realtimeClient
        realtimeClient = null
        if (activeRealtime != null) {
            Thread { activeRealtime.release() }.start()
        }
    }

    private fun disconnectControl() {
        controlClient?.close()
        pendingStart = false
        isRunning = false
        currentSessionId = null
        currentHudState = null
        currentTranscript = ""
        currentSpeechEpoch = 0
    }

    override fun onSessionReady(sessionId: String) {
        runOnUiThread {
            currentSessionId = sessionId
            if (!isRunning) {
                renderIdleState(getString(R.string.start_hint))
            }
            if (pendingStart) {
                startWorkflow()
            }
        }
    }

    override fun onHudState(state: HudState) {
        runOnUiThread {
            if (isRunning && state.phase == "WAITING_FOR_START") {
                return@runOnUiThread
            }
            currentHudState = state
            if (state.speechEpoch != currentSpeechEpoch) {
                currentSpeechEpoch = state.speechEpoch
                currentTranscript = ""
                realtimeClient?.setSpeechEpoch(state.speechEpoch)
                renderTranscript()
            }

            if (state.phase == "ERROR") {
                isRunning = false
                stopMediaClients()
            }

            renderHud(state)
        }
    }

    override fun onHudError(message: String) {
        runOnUiThread {
            isRunning = false
            stopMediaClients()
            renderIdleState(message)
        }
    }

    override fun onControlClosed(message: String) {
        runOnUiThread {
            isRunning = false
            currentSessionId = null
            currentHudState = null
            stopMediaClients()
            controlClient = null
            renderIdleState(message)
        }
    }

    private fun renderHud(state: HudState) {
        if (state.phase == "ERROR") {
            renderIdleState(idleMessage.ifBlank { "Something went wrong. Tap to restart." })
            return
        }
        val showStart = state.screen == "start"
        val showRecipe = !state.recipeName.isNullOrBlank()

        binding.tvRecipe.visibility = if (showStart || !showRecipe) View.GONE else View.VISIBLE
        binding.tvTasks.visibility = if (showStart) View.GONE else View.VISIBLE
        binding.tvTranscript.visibility = if (showStart) View.GONE else View.VISIBLE

        if (showStart) {
            renderIdleState(getString(R.string.start_hint))
            return
        }

        if (state.phase == "GUIDING") {
            hideHint()
        } else {
            showHint(phaseLabel(state.phase))
        }
        binding.tvRecipe.text = getString(R.string.recipe_label, state.recipeName.orEmpty())
        binding.tvTasks.text = renderTasks(state.tasks, state.activeTaskId)
        renderTranscript()
    }

    private fun renderIdleState(message: String) {
        idleMessage = message
        showHint(message)
        binding.tvRecipe.visibility = View.GONE
        binding.tvTasks.visibility = View.GONE
        binding.tvTranscript.visibility = View.GONE
    }

    private fun showHint(message: String) {
        binding.tvHint.text = message
        binding.tvHint.visibility = View.VISIBLE
    }

    private fun hideHint() {
        binding.tvHint.visibility = View.GONE
    }

    private fun renderTranscript() {
        binding.tvTranscript.text = currentTranscript.trim()
        if (binding.tvTranscript.text.isNullOrEmpty()) {
            binding.tvTranscript.visibility = View.GONE
        } else if (currentHudState?.screen == "running") {
            binding.tvTranscript.visibility = View.VISIBLE
        }
    }

    private fun renderTasks(tasks: List<HudTask>, activeTaskId: String?): SpannableStringBuilder {
        val builder = SpannableStringBuilder()
        tasks.forEachIndexed { index, task ->
            val prefix = when {
                task.id == activeTaskId -> "> "
                else -> "  "
            }
            val start = builder.length
            builder.append(prefix).append(task.text)
            val end = builder.length
            if (task.id == activeTaskId) {
                builder.setSpan(
                    StyleSpan(Typeface.ITALIC),
                    start + prefix.length,
                    end,
                    Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
                )
            }
            if (task.completed) {
                builder.setSpan(
                    StrikethroughSpan(),
                    start + prefix.length,
                    end,
                    Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
                )
            }
            if (index < tasks.lastIndex) {
                builder.append('\n')
            }
        }
        return builder
    }

    private fun phaseLabel(phase: String): String {
        return when (phase) {
            "CONNECTING" -> "Connecting..."
            "INVENTORY_SCAN" -> "Scanning ingredients..."
            "RECIPE_SELECTION" -> "Choosing recipe..."
            "GUIDING" -> "Guiding..."
            "COMPLETED" -> "Finished"
            "ERROR" -> "Something went wrong"
            else -> getString(R.string.start_hint)
        }
    }

    companion object {
        private const val REQ_PERMISSIONS = 1001
    }
}
