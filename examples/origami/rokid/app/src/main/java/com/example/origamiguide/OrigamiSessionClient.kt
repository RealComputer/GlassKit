package com.example.origamiguide

import android.content.Context
import android.util.Log
import java.nio.ByteBuffer
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import org.webrtc.Camera2Enumerator
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpParameters
import org.webrtc.RtpReceiver
import org.webrtc.RtpSender
import org.webrtc.SessionDescription
import org.webrtc.SurfaceTextureHelper
import org.webrtc.VideoCapturer
import org.webrtc.VideoSource
import org.webrtc.VideoTrack
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class OrigamiSessionClient(
    private val context: Context,
    private val backendBaseUrl: String,
    private val listener: Listener
) {

    data class HudState(
        val screen: String,
        val phase: String,
        val stepIndex: Int,
        val stepNumber: Int,
        val stepCount: Int,
        val hudImage: String,
        val autoCheckEnabled: Boolean,
        val trueStreak: Int,
        val message: String
    )

    interface Listener {
        fun onSessionReady(sessionId: String)
        fun onHudState(state: HudState)
        fun onHudError(message: String)
        fun onConnectionStateChanged(state: PeerConnection.IceConnectionState)
        fun onError(message: String, throwable: Throwable? = null)
    }

    companion object {
        private const val TAG = "OrigamiSessionClient"
        private const val DATA_CHANNEL_LABEL = "session-events"
        private const val CAMERA_WIDTH = 1024
        private const val CAMERA_HEIGHT = 768
        private const val CAMERA_CAPTURE_FPS = 15
        private const val CAMERA_SEND_FPS = 5
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val okHttp = OkHttpClient()
    private val eglBase: EglBase = EglBase.create()
    private val pendingMessages = ArrayDeque<String>()
    private val pendingLock = Any()

    private val peerConnectionFactory: PeerConnectionFactory by lazy {
        createPeerConnectionFactory()
    }

    private var peerConnection: PeerConnection? = null
    private var dataChannel: DataChannel? = null
    private var iceGatheringDeferred: CompletableDeferred<Unit>? = null

    private var cameraCapturer: VideoCapturer? = null
    private var cameraSurfaceHelper: SurfaceTextureHelper? = null
    private var cameraSource: VideoSource? = null
    private var cameraTrack: VideoTrack? = null

    private val mediaConstraints = MediaConstraints().apply {
        mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "false"))
        mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "false"))
    }

    fun start() {
        scope.launch {
            if (peerConnection != null) {
                Log.d(TAG, "Already started")
                return@launch
            }
            try {
                startInternal()
            } catch (t: Throwable) {
                Log.e(TAG, "Failed to start origami media session", t)
                listener.onError("Media session failed", t)
                stopInternal()
            }
        }
    }

    fun release() {
        runBlocking { stopInternal() }
        scope.cancel()
        peerConnectionFactory.dispose()
        eglBase.release()
    }

    fun sendStart() {
        sendJson(JSONObject().put("type", "session.start"))
    }

    fun sendReset() {
        sendJson(JSONObject().put("type", "session.reset"))
    }

    fun sendManualNext() {
        sendJson(JSONObject().put("type", "manual.next"))
    }

    fun sendManualPrev() {
        sendJson(JSONObject().put("type", "manual.prev"))
    }

    private suspend fun startInternal() = withContext(Dispatchers.Default) {
        val pc = createPeerConnection()
        peerConnection = pc

        createAndAddCameraTrack(pc)
        setupDataChannel(pc)

        val offer = createOffer(pc)
        setLocalDescription(pc, offer)
        waitForIceGatheringComplete(pc)

        val localSdp = pc.localDescription?.description ?: error("LocalDescription is null")
        val response = createMediaSession(localSdp)
        val answer = SessionDescription(
            SessionDescription.Type.ANSWER,
            normalizeSdp(response.answerSdp)
        )
        setRemoteDescription(pc, answer)
        listener.onSessionReady(response.sessionId)
        Log.d(TAG, "Origami WebRTC negotiation complete")
    }

    private suspend fun stopInternal() = withContext(Dispatchers.Default) {
        stopCapturer(cameraCapturer)
        cameraCapturer = null

        cameraSurfaceHelper?.dispose()
        cameraSurfaceHelper = null

        cameraTrack?.dispose()
        cameraTrack = null

        cameraSource?.dispose()
        cameraSource = null

        dataChannel?.close()
        dataChannel = null
        synchronized(pendingLock) {
            pendingMessages.clear()
        }

        peerConnection?.close()
        peerConnection?.dispose()
        peerConnection = null
    }

    private fun stopCapturer(capturer: VideoCapturer?) {
        if (capturer == null) return
        try {
            capturer.stopCapture()
        } catch (e: InterruptedException) {
            Log.w(TAG, "stopCapture interrupted", e)
        } catch (t: Throwable) {
            Log.w(TAG, "Error stopping capturer", t)
        }
        capturer.dispose()
    }

    private fun createPeerConnectionFactory(): PeerConnectionFactory {
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(context)
                .createInitializationOptions()
        )

        val encoderFactory = DefaultVideoEncoderFactory(
            eglBase.eglBaseContext,
            true,
            true
        )
        val decoderFactory = DefaultVideoDecoderFactory(eglBase.eglBaseContext)

        return PeerConnectionFactory.builder()
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .createPeerConnectionFactory()
    }

    private fun createPeerConnection(): PeerConnection {
        val iceServers = listOf(
            PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer()
        )
        val config = PeerConnection.RTCConfiguration(iceServers).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }

        return peerConnectionFactory.createPeerConnection(config, object : PeerConnection.Observer {
            override fun onSignalingChange(newState: PeerConnection.SignalingState) {}

            override fun onIceConnectionChange(newState: PeerConnection.IceConnectionState) {
                Log.d(TAG, "ICE connection state: $newState")
                listener.onConnectionStateChanged(newState)
            }

            override fun onIceConnectionReceivingChange(receiving: Boolean) {}

            override fun onIceGatheringChange(newState: PeerConnection.IceGatheringState) {
                if (newState == PeerConnection.IceGatheringState.COMPLETE) {
                    iceGatheringDeferred?.complete(Unit)
                }
            }

            override fun onIceCandidate(candidate: IceCandidate) {}
            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) {}
            override fun onAddStream(stream: MediaStream) {}
            override fun onRemoveStream(stream: MediaStream) {}
            override fun onDataChannel(dc: DataChannel) {}
            override fun onRenegotiationNeeded() {}

            override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<out MediaStream>) {
                receiver.track()?.setEnabled(true)
            }
        }) ?: error("Failed to create PeerConnection")
    }

    private fun createAndAddCameraTrack(pc: PeerConnection) {
        val capturer = createCameraCapturer()
            ?: throw IllegalStateException("No camera capturer available")
        cameraCapturer = capturer
        cameraSurfaceHelper = SurfaceTextureHelper.create(
            "OrigamiCameraCaptureThread",
            eglBase.eglBaseContext
        )
        cameraSource = peerConnectionFactory.createVideoSource(capturer.isScreencast).apply {
            adaptOutputFormat(CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_SEND_FPS)
        }
        val source = cameraSource ?: return
        capturer.initialize(cameraSurfaceHelper, context, source.capturerObserver)
        capturer.startCapture(CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_CAPTURE_FPS)

        cameraTrack = peerConnectionFactory.createVideoTrack("camera", source)
        cameraTrack?.setEnabled(true)
        cameraTrack?.let { track ->
            configureVideoSender(pc.addTrack(track))
        }
    }

    private fun createCameraCapturer(): VideoCapturer? {
        val enumerator = Camera2Enumerator(context)
        val deviceNames = enumerator.deviceNames
        val preferred = deviceNames.firstOrNull { !enumerator.isFrontFacing(it) }
            ?: deviceNames.firstOrNull()
        if (preferred == null) {
            return null
        }
        return enumerator.createCapturer(preferred, null)
    }

    private fun configureVideoSender(sender: RtpSender?) {
        if (sender == null) return
        val params = sender.parameters ?: return
        params.degradationPreference = RtpParameters.DegradationPreference.DISABLED
        sender.parameters = params
    }

    private fun setupDataChannel(pc: PeerConnection) {
        val dc = pc.createDataChannel(DATA_CHANNEL_LABEL, DataChannel.Init())
        dataChannel = dc
        dc.registerObserver(object : DataChannel.Observer {
            override fun onBufferedAmountChange(previousAmount: Long) {}

            override fun onStateChange() {
                Log.d(TAG, "DataChannel state: ${dc.state()}")
                if (dc.state() == DataChannel.State.OPEN) {
                    sendJson(
                        JSONObject()
                            .put("type", "client.media_ready")
                            .put("camera_track", "camera")
                    )
                    flushPendingMessages()
                }
            }

            override fun onMessage(buffer: DataChannel.Buffer) {
                if (buffer.binary) return
                val data = ByteArray(buffer.data.remaining())
                buffer.data.get(data)
                handleServerEvent(String(data, Charsets.UTF_8))
            }
        })
    }

    private fun sendJson(payload: JSONObject) {
        val message = payload.toString()
        val channel = dataChannel
        if (channel != null && channel.state() == DataChannel.State.OPEN) {
            channel.send(DataChannel.Buffer(ByteBuffer.wrap(message.toByteArray()), false))
        } else {
            synchronized(pendingLock) {
                pendingMessages.addLast(message)
            }
        }
    }

    private fun flushPendingMessages() {
        val channel = dataChannel ?: return
        if (channel.state() != DataChannel.State.OPEN) return
        while (true) {
            val message = synchronized(pendingLock) {
                if (pendingMessages.isEmpty()) null else pendingMessages.removeFirst()
            } ?: break
            channel.send(DataChannel.Buffer(ByteBuffer.wrap(message.toByteArray()), false))
        }
    }

    private fun handleServerEvent(jsonText: String) {
        try {
            val json = JSONObject(jsonText)
            when (json.optString("type")) {
                "session.ready" -> {
                    val sessionId = json.optString("session_id", "")
                    if (sessionId.isNotBlank()) listener.onSessionReady(sessionId)
                }

                "hud.state" -> listener.onHudState(parseHudState(json))

                "hud.error" -> {
                    listener.onHudError(json.optString("message", "Something went wrong."))
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "Failed to parse server event: $jsonText", t)
        }
    }

    private fun parseHudState(json: JSONObject): HudState {
        return HudState(
            screen = json.optString("screen", "start"),
            phase = json.optString("phase", "WAITING_FOR_START"),
            stepIndex = json.optInt("step_index", 0),
            stepNumber = json.optInt("step_number", 1),
            stepCount = json.optInt("step_count", 7),
            hudImage = json.optString("hud_image", "origami_step_1"),
            autoCheckEnabled = json.optBoolean("auto_check_enabled", true),
            trueStreak = json.optInt("true_streak", 0),
            message = json.optString("message", "")
        )
    }

    private suspend fun createMediaSession(offerSdp: String): MediaSessionResponse =
        withContext(Dispatchers.IO) {
            val mediaType = "application/json".toMediaType()
            val body = JSONObject()
                .put("offer_sdp", offerSdp)
                .toString()
                .toRequestBody(mediaType)
            val request = Request.Builder()
                .url("${backendBaseUrl.trim().trimEnd('/')}/session/media")
                .post(body)
                .build()

            okHttp.newCall(request).execute().use { response ->
                val responseBody = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val msg = "Media session request failed: HTTP ${response.code} ${response.message}"
                    Log.e(TAG, "$msg body=$responseBody")
                    throw IllegalStateException(msg)
                }
                val json = JSONObject(responseBody)
                MediaSessionResponse(
                    sessionId = json.optString("session_id", ""),
                    answerSdp = json.optString("answer_sdp", "")
                )
            }
        }

    private suspend fun createOffer(pc: PeerConnection): SessionDescription =
        suspendCancellableCoroutine { cont ->
            pc.createOffer(object : org.webrtc.SdpObserver {
                override fun onCreateSuccess(desc: SessionDescription?) {
                    if (desc != null && !cont.isCompleted) cont.resume(desc)
                }

                override fun onCreateFailure(error: String?) {
                    if (!cont.isCompleted) {
                        cont.resumeWithException(RuntimeException("createOffer failed: $error"))
                    }
                }

                override fun onSetSuccess() {}
                override fun onSetFailure(error: String?) {}
            }, mediaConstraints)
        }

    private suspend fun setLocalDescription(pc: PeerConnection, desc: SessionDescription) =
        suspendCancellableCoroutine<Unit> { cont ->
            pc.setLocalDescription(object : org.webrtc.SdpObserver {
                override fun onSetSuccess() {
                    if (!cont.isCompleted) cont.resume(Unit)
                }

                override fun onSetFailure(error: String?) {
                    if (!cont.isCompleted) {
                        cont.resumeWithException(RuntimeException("setLocalDescription failed: $error"))
                    }
                }

                override fun onCreateSuccess(desc: SessionDescription?) {}
                override fun onCreateFailure(error: String?) {}
            }, desc)
        }

    private suspend fun setRemoteDescription(pc: PeerConnection, desc: SessionDescription) =
        suspendCancellableCoroutine<Unit> { cont ->
            pc.setRemoteDescription(object : org.webrtc.SdpObserver {
                override fun onSetSuccess() {
                    if (!cont.isCompleted) cont.resume(Unit)
                }

                override fun onSetFailure(error: String?) {
                    if (!cont.isCompleted) {
                        cont.resumeWithException(RuntimeException("setRemoteDescription failed: $error"))
                    }
                }

                override fun onCreateSuccess(desc: SessionDescription?) {}
                override fun onCreateFailure(error: String?) {}
            }, desc)
        }

    private suspend fun waitForIceGatheringComplete(pc: PeerConnection) {
        val deferred = CompletableDeferred<Unit>()
        iceGatheringDeferred = deferred
        if (pc.iceGatheringState() == PeerConnection.IceGatheringState.COMPLETE) {
            iceGatheringDeferred = null
            return
        }
        withTimeoutOrNull(15_000) { deferred.await() }
        iceGatheringDeferred = null
    }

    private fun normalizeSdp(raw: String): String {
        val text = raw.trim()
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\r\n", "\n")
            .replace('\r', '\n')
        val lines = text.split('\n').map { it.trim() }.filter { it.isNotEmpty() }
        return if (lines.isEmpty()) "" else lines.joinToString("\r\n", postfix = "\r\n")
    }

    private data class MediaSessionResponse(
        val sessionId: String,
        val answerSdp: String
    )
}
