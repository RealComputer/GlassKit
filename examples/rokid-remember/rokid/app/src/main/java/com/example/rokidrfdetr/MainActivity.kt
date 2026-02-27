package com.example.rokidrfdetr

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.example.rokidrfdetr.databinding.ActivityMainBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.Locale

class MainActivity : AppCompatActivity() {

    companion object {
        private const val REQ_PERMISSIONS = 1001
        private const val UI_TICK_MS = 500L
    }

    private lateinit var binding: ActivityMainBinding

    private val activityScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val uiHandler = Handler(Looper.getMainLooper())
    private val connectivityManager by lazy { getSystemService(ConnectivityManager::class.java) }

    private val backendBaseUrl: String = BuildConfig.BACKEND_BASE_URL.trim().trimEnd('/')

    private var startedLoops = false
    private var networkAvailable = false
    private var backendHealthy = false

    private var healthJob: Job? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    private val uiTickRunnable = object : Runnable {
        override fun run() {
            renderUi()
            uiHandler.postDelayed(this, UI_TICK_MS)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        renderUi()
        ensurePermissions()
    }

    override fun onDestroy() {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        uiHandler.removeCallbacksAndMessages(null)
        healthJob?.cancel()
        stopNetworkMonitoring()
        activityScope.cancel()
        super.onDestroy()
    }

    override fun onResume() {
        super.onResume()
        if (startedLoops) {
            uiHandler.removeCallbacks(uiTickRunnable)
            uiHandler.post(uiTickRunnable)
        }
    }

    override fun onPause() {
        uiHandler.removeCallbacks(uiTickRunnable)
        super.onPause()
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        val state = RecordingService.snapshotState()
        return when (keyCode) {
            KeyEvent.KEYCODE_DPAD_UP -> {
                if (!state.isRecording) {
                    sendSetModeIntent(RecorderMode.VIDEO)
                }
                true
            }

            KeyEvent.KEYCODE_DPAD_DOWN -> {
                if (!state.isRecording) {
                    sendSetModeIntent(RecorderMode.AUDIO)
                }
                true
            }

            KeyEvent.KEYCODE_ENTER -> {
                if (state.isRecording) {
                    sendStopIntent()
                } else if (isReadyToRecord()) {
                    sendStartIntent()
                }
                renderUi()
                true
            }

            else -> super.onKeyUp(keyCode, event)
        }
    }

    private fun ensurePermissions() {
        val missing = (criticalPermissions() + optionalPermissions()).filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (missing.isEmpty()) {
            startLoopsIfNeeded()
            return
        }

        ActivityCompat.requestPermissions(this, missing.toTypedArray(), REQ_PERMISSIONS)
    }

    private fun criticalPermissions(): List<String> {
        return listOf(
            Manifest.permission.CAMERA,
            Manifest.permission.RECORD_AUDIO,
        )
    }

    private fun optionalPermissions(): List<String> {
        val permissions = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        return permissions
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_PERMISSIONS) return

        val criticalSet = criticalPermissions().toSet()
        val deniedCriticalPermission = permissions.indices.any { index ->
            grantResults.getOrNull(index) != PackageManager.PERMISSION_GRANTED &&
                criticalSet.contains(permissions[index])
        }

        if (!deniedCriticalPermission) {
            startLoopsIfNeeded()
        } else {
            renderUi()
        }
    }

    private fun startLoopsIfNeeded() {
        if (startedLoops) return
        startedLoops = true

        startNetworkMonitoring()
        startHealthPolling()
        uiHandler.post(uiTickRunnable)
    }

    private fun startNetworkMonitoring() {
        if (networkCallback != null) return

        networkAvailable = hasUsableNetwork()

        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                networkAvailable = true
                renderUi()
            }

            override fun onLost(network: Network) {
                networkAvailable = hasUsableNetwork()
                if (!networkAvailable) {
                    backendHealthy = false
                }
                renderUi()
            }

            override fun onCapabilitiesChanged(network: Network, networkCapabilities: NetworkCapabilities) {
                val hasInternet = networkCapabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                val validated = networkCapabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
                networkAvailable = hasInternet && validated
                renderUi()
            }
        }

        connectivityManager.registerDefaultNetworkCallback(callback)
        networkCallback = callback
    }

    private fun stopNetworkMonitoring() {
        val callback = networkCallback ?: return
        connectivityManager.unregisterNetworkCallback(callback)
        networkCallback = null
    }

    private fun hasUsableNetwork(): Boolean {
        val network = connectivityManager.activeNetwork ?: return false
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }

    private fun startHealthPolling() {
        healthJob?.cancel()
        healthJob = activityScope.launch {
            while (isActive) {
                backendHealthy = if (networkAvailable) {
                    BackendApiClient.checkHealth(backendBaseUrl)
                } else {
                    false
                }
                renderUi()
                delay(if (backendHealthy) 5_000 else 1_500)
            }
        }
    }

    private fun sendSetModeIntent(mode: RecorderMode) {
        val intent = Intent(this, RecordingService::class.java)
            .setAction(RecordingService.ACTION_SET_MODE)
            .putExtra(RecordingService.EXTRA_MODE, mode.wireValue)
        startService(intent)
    }

    private fun sendStartIntent() {
        val intent = Intent(this, RecordingService::class.java)
            .setAction(RecordingService.ACTION_START_RECORDING)
        ContextCompat.startForegroundService(this, intent)
    }

    private fun sendStopIntent() {
        val intent = Intent(this, RecordingService::class.java)
            .setAction(RecordingService.ACTION_STOP_RECORDING)
        startService(intent)
    }

    private fun isReadyToRecord(): Boolean {
        val hasPermissions = criticalPermissions().all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
        return hasPermissions && networkAvailable && backendHealthy
    }

    private fun renderUi() {
        val state = RecordingService.snapshotState()

        if (state.isRecording) {
            val start = state.activeSegmentStartUnix ?: (System.currentTimeMillis() / 1000)
            val elapsed = (System.currentTimeMillis() / 1000 - start).coerceAtLeast(0)

            binding.tvMain.text = "REC ${state.mode.wireValue} ${formatElapsed(elapsed)}"
            binding.tvHint.text = "ENTER: stop"
            binding.tvHint.alpha = 0.7f

            val topParts = mutableListOf("pending uploads: ${state.pendingUploads}")
            state.lastError?.takeIf { it.isNotBlank() }?.let(topParts::add)
            binding.tvTop.text = topParts.joinToString(" | ")
            binding.tvTop.alpha = 0.7f
            return
        }

        val readiness = when {
            !hasAllPermissionsGranted() -> "grant camera/mic permissions"
            !networkAvailable -> "waiting for network"
            !backendHealthy -> "waiting for $backendBaseUrl/health"
            else -> "ready"
        }

        binding.tvMain.text = "mode: ${state.mode.wireValue}\n$readiness"
        binding.tvHint.text = "UP: video  DOWN: audio  ENTER: start"
        binding.tvHint.alpha = 1.0f

        val topParts = mutableListOf("pending uploads: ${state.pendingUploads}")
        state.lastError?.takeIf { it.isNotBlank() }?.let(topParts::add)
        binding.tvTop.text = topParts.joinToString(" | ")
        binding.tvTop.alpha = 1.0f
    }

    private fun hasAllPermissionsGranted(): Boolean {
        return criticalPermissions().all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun formatElapsed(totalSeconds: Long): String {
        val hours = totalSeconds / 3600
        val minutes = (totalSeconds % 3600) / 60
        val seconds = totalSeconds % 60
        return String.format(Locale.US, "%02d:%02d:%02d", hours, minutes, seconds)
    }
}
