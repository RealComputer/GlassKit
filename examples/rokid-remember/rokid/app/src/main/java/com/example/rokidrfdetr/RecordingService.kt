package com.example.rokidrfdetr

import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import android.util.Size
import android.view.Surface
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.math.max

class RecordingService : Service() {

    data class ServiceState(
        val mode: RecorderMode = RecorderMode.VIDEO,
        val isRecording: Boolean = false,
        val activeSegmentStartUnix: Long? = null,
        val pendingUploads: Int = 0,
        val lastError: String? = null,
    )

    companion object {
        const val ACTION_INIT = "com.example.rokidrfdetr.action.INIT"
        const val ACTION_SET_MODE = "com.example.rokidrfdetr.action.SET_MODE"
        const val ACTION_START_RECORDING = "com.example.rokidrfdetr.action.START_RECORDING"
        const val ACTION_STOP_RECORDING = "com.example.rokidrfdetr.action.STOP_RECORDING"
        const val EXTRA_MODE = "com.example.rokidrfdetr.extra.MODE"

        private const val TAG = "RecordingService"
        private const val CHANNEL_ID = "recording_channel"
        private const val NOTIFICATION_ID = 1201
        private const val SEGMENT_DURATION_MS = 10 * 60 * 1000L
        private val COMPLETED_SEGMENT_RE = Regex("^(\\d+)-(\\d+)\\.(mp4|m4a)$")

        private val stateLock = Any()
        private var sharedState = ServiceState()

        fun snapshotState(): ServiceState = synchronized(stateLock) { sharedState }

        private fun setSharedState(state: ServiceState) {
            synchronized(stateLock) {
                sharedState = state
            }
        }
    }

    private data class SegmentMeta(
        val startUnix: Long,
        val endUnix: Long,
        val mode: RecorderMode,
    )

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val recorderMutex = Mutex()
    private val backendBaseUrl: String = BuildConfig.BACKEND_BASE_URL.trim().trimEnd('/')
    private val segmentDir by lazy { File(filesDir, "segments").apply { mkdirs() } }

    private var selectedMode = RecorderMode.VIDEO
    private var isRecording = false
    private var activeMode: RecorderMode? = null
    private var activeStartUnix: Long? = null
    private var activeTempFile: File? = null

    private var audioRecorder: MediaRecorder? = null
    private var videoRecorder: VideoSegmentRecorder? = null

    private var segmentRotationJob: Job? = null
    private var uploadLoopJob: Job? = null
    private var lastError: String? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startUploadLoopIfNeeded()
        refreshSharedState()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val requestIntent = intent
        when (requestIntent?.action ?: ACTION_INIT) {
            ACTION_SET_MODE -> {
                val mode = RecorderMode.fromWireValue(requestIntent?.getStringExtra(EXTRA_MODE))
                if (mode != null) {
                    serviceScope.launch {
                        recorderMutex.withLock {
                            setModeLocked(mode)
                        }
                    }
                }
            }

            ACTION_START_RECORDING -> {
                startForeground(NOTIFICATION_ID, buildNotification("Starting..."))
                serviceScope.launch {
                    recorderMutex.withLock {
                        startRecordingLocked()
                    }
                }
            }

            ACTION_STOP_RECORDING -> {
                serviceScope.launch {
                    recorderMutex.withLock {
                        stopRecordingLocked(explicitStop = true)
                    }
                }
            }

            ACTION_INIT -> {
                refreshSharedState()
            }
        }

        return START_STICKY
    }

    override fun onDestroy() {
        runBlocking {
            recorderMutex.withLock {
                stopRecordingLocked(explicitStop = false)
            }
        }
        segmentRotationJob?.cancel()
        uploadLoopJob?.cancel()
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private suspend fun setModeLocked(mode: RecorderMode) {
        if (isRecording) {
            setError("Cannot change mode while recording")
            return
        }
        selectedMode = mode
        lastError = null
        refreshSharedState()
    }

    private suspend fun startRecordingLocked() {
        if (isRecording) {
            refreshForegroundNotification()
            return
        }

        lastError = null
        isRecording = true
        val started = startNewSegmentLocked(selectedMode)
        if (!started) {
            isRecording = false
            stopForeground(STOP_FOREGROUND_REMOVE)
        }
        refreshSharedState()
        refreshForegroundNotification()
    }

    private suspend fun stopRecordingLocked(explicitStop: Boolean) {
        if (!isRecording) {
            if (explicitStop) {
                stopForeground(STOP_FOREGROUND_REMOVE)
            }
            refreshSharedState()
            return
        }

        isRecording = false
        segmentRotationJob?.cancel()
        segmentRotationJob = null
        finishActiveSegmentLocked()

        stopForeground(STOP_FOREGROUND_REMOVE)
        refreshSharedState()
    }

    private suspend fun startNewSegmentLocked(mode: RecorderMode): Boolean {
        val startUnix = System.currentTimeMillis() / 1000
        val tempFile = File(segmentDir, "$startUnix.${mode.extension}.part")
        tempFile.delete()

        return try {
            when (mode) {
                RecorderMode.AUDIO -> {
                    audioRecorder = createAudioRecorder(tempFile)
                    audioRecorder?.start()
                }

                RecorderMode.VIDEO -> {
                    val recorder = VideoSegmentRecorder(applicationContext, tempFile)
                    recorder.start()
                    videoRecorder = recorder
                }
            }

            activeMode = mode
            activeStartUnix = startUnix
            activeTempFile = tempFile
            scheduleSegmentRotationLocked()
            lastError = null
            true
        } catch (t: Throwable) {
            Log.e(TAG, "Failed to start segment", t)
            audioRecorder?.safeRelease()
            audioRecorder = null
            videoRecorder?.safeRelease()
            videoRecorder = null
            activeMode = null
            activeStartUnix = null
            activeTempFile = null
            tempFile.delete()
            setError("Failed to start recording")
            false
        }
    }

    private suspend fun finishActiveSegmentLocked() {
        val mode = activeMode ?: return
        val startUnix = activeStartUnix ?: return
        val tempFile = activeTempFile ?: return

        val success = when (mode) {
            RecorderMode.AUDIO -> {
                val recorder = audioRecorder
                audioRecorder = null
                recorder?.safeStop() ?: false
            }

            RecorderMode.VIDEO -> {
                val recorder = videoRecorder
                videoRecorder = null
                recorder?.stop() ?: false
            }
        }

        activeMode = null
        activeStartUnix = null
        activeTempFile = null

        if (!success || !tempFile.exists()) {
            tempFile.delete()
            return
        }

        val endUnix = max(startUnix + 1, System.currentTimeMillis() / 1000)
        val finalFile = File(segmentDir, "$startUnix-$endUnix.${mode.extension}")

        try {
            Files.move(
                tempFile.toPath(),
                finalFile.toPath(),
                StandardCopyOption.REPLACE_EXISTING,
            )
        } catch (t: Throwable) {
            Log.e(TAG, "Failed to finalize segment ${tempFile.name}", t)
            tempFile.delete()
            setError("Failed to finalize segment")
        }
    }

    private fun scheduleSegmentRotationLocked() {
        segmentRotationJob?.cancel()
        segmentRotationJob = serviceScope.launch {
            delay(SEGMENT_DURATION_MS)
            recorderMutex.withLock {
                if (!isRecording) return@withLock
                finishActiveSegmentLocked()

                val restarted = startNewSegmentLocked(selectedMode)
                if (!restarted) {
                    isRecording = false
                    stopForeground(STOP_FOREGROUND_REMOVE)
                }

                refreshSharedState()
                refreshForegroundNotification()
            }
        }
    }

    private fun createAudioRecorder(outputFile: File): MediaRecorder {
        return MediaRecorder().apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setAudioEncodingBitRate(128_000)
            setAudioSamplingRate(44_100)
            setOutputFile(outputFile.absolutePath)
            prepare()
        }
    }

    private fun startUploadLoopIfNeeded() {
        if (uploadLoopJob != null) return

        uploadLoopJob = serviceScope.launch {
            while (isActive) {
                val pending = listCompletedSegments()
                if (pending.isEmpty()) {
                    refreshSharedState()
                    delay(2_000)
                    continue
                }

                val healthy = BackendApiClient.checkHealth(backendBaseUrl)
                if (!healthy) {
                    setError("Backend unavailable; retrying uploads")
                    delay(3_000)
                    continue
                }

                var uploadedAny = false
                for (file in pending) {
                    val meta = parseSegmentMeta(file) ?: continue
                    val uploaded = BackendApiClient.uploadSegment(
                        baseUrl = backendBaseUrl,
                        file = file,
                        mode = meta.mode,
                        startUnix = meta.startUnix,
                        endUnix = meta.endUnix,
                    )

                    if (!uploaded) {
                        setError("Upload failed; retrying ${file.name}")
                        delay(5_000)
                        break
                    }

                    uploadedAny = true
                    if (!file.delete()) {
                        Log.w(TAG, "Failed to delete uploaded file ${file.absolutePath}")
                    }
                    lastError = null
                }

                refreshSharedState()
                if (!uploadedAny) {
                    delay(2_000)
                }
            }
        }
    }

    private fun listCompletedSegments(): List<File> {
        val files = segmentDir.listFiles() ?: return emptyList()
        return files
            .filter { parseSegmentMeta(it) != null }
            .sortedBy { it.name }
    }

    private fun parseSegmentMeta(file: File): SegmentMeta? {
        val match = COMPLETED_SEGMENT_RE.matchEntire(file.name) ?: return null
        val start = match.groupValues[1].toLongOrNull() ?: return null
        val end = match.groupValues[2].toLongOrNull() ?: return null
        val ext = match.groupValues[3]
        val mode = when (ext) {
            "mp4" -> RecorderMode.VIDEO
            "m4a" -> RecorderMode.AUDIO
            else -> return null
        }
        return SegmentMeta(start, end, mode)
    }

    private fun refreshSharedState() {
        setSharedState(
            ServiceState(
                mode = selectedMode,
                isRecording = isRecording,
                activeSegmentStartUnix = activeStartUnix,
                pendingUploads = listCompletedSegments().size,
                lastError = lastError,
            )
        )
    }

    private fun setError(message: String) {
        lastError = message
        refreshSharedState()
        refreshForegroundNotification()
    }

    private fun refreshForegroundNotification() {
        if (!isRecording) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification("Recording ${selectedMode.wireValue}"))
    }

    private fun buildNotification(message: String): android.app.Notification {
        val launchIntent = Intent(this, MainActivity::class.java)
        val launchPendingIntent = PendingIntent.getActivity(
            this,
            0,
            launchIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Rokid Recorder")
            .setContentText(message)
            .setContentIntent(launchPendingIntent)
            .setOngoing(isRecording)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val manager = getSystemService(NotificationManager::class.java)
        val existing = manager.getNotificationChannel(CHANNEL_ID)
        if (existing != null) return

        val channel = NotificationChannel(
            CHANNEL_ID,
            "Recording",
            NotificationManager.IMPORTANCE_LOW,
        )
        manager.createNotificationChannel(channel)
    }

    private fun MediaRecorder.safeStop(): Boolean {
        return try {
            stop()
            true
        } catch (t: Throwable) {
            Log.w(TAG, "Audio recorder stop failed", t)
            false
        } finally {
            safeRelease()
        }
    }

    private fun MediaRecorder.safeRelease() {
        try {
            reset()
        } catch (_: Throwable) {
        }
        try {
            release()
        } catch (_: Throwable) {
        }
    }
}

private class VideoSegmentRecorder(
    context: Context,
    private val outputFile: File,
) {
    companion object {
        private const val TAG = "VideoSegmentRecorder"
    }

    private val cameraManager = context.getSystemService(CameraManager::class.java)

    private var mediaRecorder: MediaRecorder? = null
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null

    suspend fun start() {
        val cameraId = selectCameraId()
        val size = chooseVideoSize(cameraId)
        val recorder = createMediaRecorder(outputFile, size)
        mediaRecorder = recorder

        try {
            val device = openCamera(cameraId)
            cameraDevice = device

            val recorderSurface = recorder.surface
            val session = createCaptureSession(device, recorderSurface)
            captureSession = session

            val request = device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
                addTarget(recorderSurface)
                set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
            }.build()

            session.setRepeatingRequest(request, null, Handler(Looper.getMainLooper()))
            recorder.start()
        } catch (t: Throwable) {
            safeRelease()
            throw t
        }
    }

    suspend fun stop(): Boolean {
        val recorder = mediaRecorder
        var success = true

        try {
            captureSession?.stopRepeating()
        } catch (_: Throwable) {
        }

        try {
            captureSession?.abortCaptures()
        } catch (_: Throwable) {
        }

        if (recorder != null) {
            success = try {
                recorder.stop()
                true
            } catch (t: Throwable) {
                Log.w(TAG, "Video recorder stop failed", t)
                false
            }
        }

        safeRelease()
        return success
    }

    fun safeRelease() {
        try {
            mediaRecorder?.reset()
        } catch (_: Throwable) {
        }
        try {
            mediaRecorder?.release()
        } catch (_: Throwable) {
        }
        mediaRecorder = null

        try {
            captureSession?.close()
        } catch (_: Throwable) {
        }
        captureSession = null

        try {
            cameraDevice?.close()
        } catch (_: Throwable) {
        }
        cameraDevice = null
    }

    private fun selectCameraId(): String {
        val ids = cameraManager.cameraIdList
        if (ids.isEmpty()) {
            error("No camera available")
        }

        for (id in ids) {
            val characteristics = cameraManager.getCameraCharacteristics(id)
            val facing = characteristics.get(CameraCharacteristics.LENS_FACING)
            if (facing == CameraCharacteristics.LENS_FACING_BACK) {
                return id
            }
        }

        return ids.first()
    }

    private fun chooseVideoSize(cameraId: String): Size {
        val characteristics = cameraManager.getCameraCharacteristics(cameraId)
        val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val sizes = map?.getOutputSizes(MediaRecorder::class.java) ?: emptyArray()

        if (sizes.isEmpty()) {
            return Size(1280, 720)
        }

        sizes.firstOrNull { it.width == 1280 && it.height == 720 }?.let { return it }

        val maxArea = 1280 * 720
        val underLimit = sizes
            .filter { it.width * it.height <= maxArea }
            .maxByOrNull { it.width * it.height }
        if (underLimit != null) return underLimit

        return sizes.maxBy { it.width * it.height }
    }

    private fun createMediaRecorder(outputFile: File, size: Size): MediaRecorder {
        return MediaRecorder().apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setVideoSource(MediaRecorder.VideoSource.SURFACE)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setVideoEncoder(MediaRecorder.VideoEncoder.H264)
            setAudioEncodingBitRate(128_000)
            setAudioSamplingRate(44_100)
            setVideoEncodingBitRate(4_000_000)
            setVideoFrameRate(30)
            setVideoSize(size.width, size.height)
            setOutputFile(outputFile.absolutePath)
            prepare()
        }
    }

    @SuppressLint("MissingPermission")
    private suspend fun openCamera(cameraId: String): CameraDevice = suspendCancellableCoroutine { cont ->
        val callback = object : CameraDevice.StateCallback() {
            override fun onOpened(camera: CameraDevice) {
                if (!cont.isCompleted) {
                    cont.resume(camera)
                } else {
                    camera.close()
                }
            }

            override fun onDisconnected(camera: CameraDevice) {
                camera.close()
                if (!cont.isCompleted) {
                    cont.resumeWithException(IllegalStateException("Camera disconnected"))
                }
            }

            override fun onError(camera: CameraDevice, error: Int) {
                camera.close()
                if (!cont.isCompleted) {
                    cont.resumeWithException(IllegalStateException("Camera error $error"))
                }
            }
        }

        cameraManager.openCamera(cameraId, callback, Handler(Looper.getMainLooper()))

        cont.invokeOnCancellation {
            // Camera close is handled in callbacks when available.
        }
    }

    private suspend fun createCaptureSession(
        camera: CameraDevice,
        recorderSurface: Surface,
    ): CameraCaptureSession = suspendCancellableCoroutine { cont ->
        val callback = object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(session: CameraCaptureSession) {
                if (!cont.isCompleted) {
                    cont.resume(session)
                } else {
                    session.close()
                }
            }

            override fun onConfigureFailed(session: CameraCaptureSession) {
                session.close()
                if (!cont.isCompleted) {
                    cont.resumeWithException(IllegalStateException("Capture session config failed"))
                }
            }
        }

        camera.createCaptureSession(
            listOf(recorderSurface),
            callback,
            Handler(Looper.getMainLooper()),
        )
    }
}
