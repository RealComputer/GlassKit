package com.example.origamiguide

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import com.example.origamiguide.OrigamiSessionClient.HudState
import com.example.origamiguide.databinding.ActivityMainBinding
import org.webrtc.PeerConnection

class MainActivity : ComponentActivity(), OrigamiSessionClient.Listener {

    private lateinit var binding: ActivityMainBinding

    private var sessionClient: OrigamiSessionClient? = null
    private var currentHudState: HudState? = null
    private var pendingStart = false
    private var isMediaRunning = false

    private val backendBaseUrl: String = BuildConfig.BACKEND_BASE_URL
    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            if (pendingStart) {
                startWorkflow()
            }
        } else {
            pendingStart = false
            renderStart("Camera permission is required.")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        binding.tvTitle.text = getString(R.string.app_name)
        binding.tvControls.text = getString(R.string.controls_hint)
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    handleDoubleTap()
                }
            }
        )

        renderStart(getString(R.string.start_hint))
        ensureCameraPermission()
    }

    override fun onDestroy() {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        stopMediaSession()
        super.onDestroy()
    }

    override fun onStop() {
        stopMediaSession()
        super.onStop()
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_ENTER -> {
                // Rokid tap has no workflow action.
                true
            }

            KeyEvent.KEYCODE_DPAD_DOWN -> {
                // Rokid swipe forward.
                sessionClient?.sendManualNext()
                true
            }

            KeyEvent.KEYCODE_DPAD_UP -> {
                // Rokid swipe backward.
                sessionClient?.sendManualPrev()
                true
            }

            KeyEvent.KEYCODE_BACK -> {
                // Rokid double tap; Android back callback uses the same handler.
                handleDoubleTap()
                true
            }

            else -> super.onKeyUp(keyCode, event)
        }
    }

    private fun handleDoubleTap() {
        val phase = currentHudState?.phase
        // Double tap starts from idle/waiting; every other state resets.
        if (!isMediaRunning || phase == null || phase == "WAITING_FOR_START") {
            startWorkflow()
            return
        }
        sessionClient?.sendReset()
    }

    private fun startWorkflow() {
        if (!hasCameraPermission()) {
            pendingStart = true
            ensureCameraPermission()
            return
        }

        val existing = sessionClient
        if (existing != null && isMediaRunning) {
            pendingStart = false
            existing.sendStart()
            return
        }

        pendingStart = true
        renderStart(getString(R.string.connecting_backend))
        startMediaSession()
    }

    private fun startMediaSession() {
        isMediaRunning = true
        currentHudState = null
        sessionClient = OrigamiSessionClient(
            context = applicationContext,
            backendBaseUrl = backendBaseUrl,
            listener = this
        ).also { client ->
            client.start()
            client.sendStart()
        }
    }

    private fun stopMediaSession() {
        val active = sessionClient
        sessionClient = null
        isMediaRunning = false
        pendingStart = false
        currentHudState = null
        if (active != null) {
            Thread { active.release() }.start()
        }
    }

    private fun ensureCameraPermission() {
        if (hasCameraPermission()) return
        cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
    }

    private fun hasCameraPermission(): Boolean {
        return checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
    }

    override fun onSessionReady(sessionId: String) {
        runOnUiThread {
            if (pendingStart) {
                sessionClient?.sendStart()
            }
        }
    }

    override fun onHudState(state: HudState) {
        runOnUiThread {
            currentHudState = state
            pendingStart = false
            renderHud(state)
        }
    }

    override fun onHudError(message: String) {
        runOnUiThread {
            renderStart(message)
        }
    }

    override fun onConnectionStateChanged(state: PeerConnection.IceConnectionState) {
        runOnUiThread {
            if (state == PeerConnection.IceConnectionState.FAILED) {
                handleMediaStopped("Video link failed. Double tap to reconnect.")
            }
        }
    }

    override fun onError(message: String, throwable: Throwable?) {
        runOnUiThread {
            handleMediaStopped(message)
        }
    }

    private fun handleMediaStopped(message: String) {
        val active = sessionClient
        sessionClient = null
        isMediaRunning = false
        pendingStart = false
        currentHudState = null
        if (active != null) {
            Thread { active.release() }.start()
        }
        renderStart(message)
    }

    private fun renderHud(state: HudState) {
        if (state.screen == "start") {
            renderStart(getString(R.string.start_hint))
            return
        }

        binding.tvHint.visibility = View.GONE
        binding.tvStep.visibility = View.VISIBLE
        binding.ivStep.visibility = View.VISIBLE
        binding.tvMessage.visibility = if (state.message.isBlank()) View.INVISIBLE else View.VISIBLE
        binding.tvControls.visibility = View.VISIBLE

        binding.tvStep.text = getString(
            R.string.step_label,
            state.stepNumber,
            state.stepCount
        )
        binding.tvMessage.text = state.message
        binding.tvControls.text = if (state.autoCheckEnabled) {
            getString(R.string.controls_auto_on)
        } else {
            getString(R.string.controls_auto_off)
        }

        val resId = resources.getIdentifier(state.hudImage, "drawable", packageName)
        if (resId != 0) {
            binding.ivStep.setImageResource(resId)
        }
    }

    private fun renderStart(message: String) {
        binding.tvHint.text = message
        binding.tvHint.visibility = View.VISIBLE
        binding.tvStep.visibility = View.GONE
        binding.ivStep.visibility = View.GONE
        binding.tvMessage.visibility = View.INVISIBLE
        binding.tvControls.visibility = View.VISIBLE
        binding.tvControls.text = getString(R.string.start_controls_hint)
    }
}
