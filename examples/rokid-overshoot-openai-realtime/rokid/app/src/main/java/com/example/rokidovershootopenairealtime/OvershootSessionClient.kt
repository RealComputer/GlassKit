package com.example.rokidovershootopenairealtime

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import org.webrtc.Camera2Enumerator
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

class OvershootSessionClient(
    private val context: Context,
    private val backendBaseUrl: String,
    private val sessionId: String,
    private val listener: Listener
) {

    interface Listener {
        fun onConnectionStateChanged(state: PeerConnection.IceConnectionState)
        fun onError(message: String, throwable: Throwable? = null)
    }

    companion object {
        private const val TAG = "OvershootSessionClient"
        private const val OVERSHOOT_TURN_USERNAME = "overshoot"
        private const val OVERSHOOT_TURN_CREDENTIAL = "overshoot"
        private const val CAPTURE_WIDTH = 1024
        private const val CAPTURE_HEIGHT = 768
        private const val CAPTURE_FPS = 15
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val okHttp = OkHttpClient()
    private val eglBase: EglBase = EglBase.create()

    private val peerConnectionFactory: PeerConnectionFactory by lazy {
        createPeerConnectionFactory()
    }

    private var peerConnection: PeerConnection? = null
    private var localVideoSource: VideoSource? = null
    private var localVideoTrack: VideoTrack? = null
    private var localVideoCapturer: VideoCapturer? = null
    private var surfaceTextureHelper: SurfaceTextureHelper? = null
    private var iceGatheringDeferred: CompletableDeferred<Unit>? = null

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
                Log.e(TAG, "Failed to start vision session", t)
                listener.onError("Failed to start vision session", t)
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

    private suspend fun startInternal() = withContext(Dispatchers.Default) {
        val pc = createPeerConnection()
        peerConnection = pc

        createAndAddVideoTrack(pc)

        val offer = createOffer(pc)
        setLocalDescription(pc, offer)
        waitForIceGatheringComplete(pc)

        val localSdp = pc.localDescription?.description ?: error("LocalDescription is null")
        val answerSdp = createVisionSession(localSdp)
        val answer = SessionDescription(SessionDescription.Type.ANSWER, answerSdp)
        setRemoteDescription(pc, answer)
    }

    private suspend fun stopInternal() = withContext(Dispatchers.Default) {
        try {
            localVideoCapturer?.let { capturer ->
                try {
                    capturer.stopCapture()
                } catch (e: InterruptedException) {
                    Log.w(TAG, "stopCapture interrupted", e)
                }
                capturer.dispose()
            }
        } catch (t: Throwable) {
            Log.w(TAG, "Error stopping video capturer", t)
        }
        localVideoCapturer = null

        surfaceTextureHelper?.dispose()
        surfaceTextureHelper = null

        localVideoTrack?.dispose()
        localVideoTrack = null
        localVideoSource?.dispose()
        localVideoSource = null

        peerConnection?.close()
        peerConnection?.dispose()
        peerConnection = null
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
            createTurnIceServer("turn:turn.overshoot.ai:3478?transport=udp"),
            createTurnIceServer("turn:turn.overshoot.ai:3478?transport=tcp"),
            createTurnIceServer("turns:turn.overshoot.ai:443?transport=udp"),
            createTurnIceServer("turns:turn.overshoot.ai:443?transport=tcp")
        )

        val config = PeerConnection.RTCConfiguration(iceServers).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }

        return peerConnectionFactory.createPeerConnection(config, object : PeerConnection.Observer {
            override fun onSignalingChange(newState: PeerConnection.SignalingState) {}

            override fun onIceConnectionChange(newState: PeerConnection.IceConnectionState) {
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

            override fun onDataChannel(dc: org.webrtc.DataChannel) {}

            override fun onRenegotiationNeeded() {}

            override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<out MediaStream>) {
                when (val track = receiver.track()) {
                    is VideoTrack -> track.setEnabled(true)
                }
            }
        }) ?: error("Failed to create PeerConnection")
    }

    private fun createTurnIceServer(uri: String): PeerConnection.IceServer {
        return PeerConnection.IceServer.builder(uri)
            .setUsername(OVERSHOOT_TURN_USERNAME)
            .setPassword(OVERSHOOT_TURN_CREDENTIAL)
            .createIceServer()
    }

    private fun createAndAddVideoTrack(pc: PeerConnection) {
        val videoCapturer = createCameraCapturer()
            ?: throw IllegalStateException("No camera capturer available")
        localVideoCapturer = videoCapturer

        surfaceTextureHelper = SurfaceTextureHelper.create(
            "OvershootCaptureThread",
            eglBase.eglBaseContext
        )

        localVideoSource = peerConnectionFactory.createVideoSource(videoCapturer.isScreencast).apply {
            adaptOutputFormat(CAPTURE_WIDTH, CAPTURE_HEIGHT, CAPTURE_FPS)
        }

        localVideoSource?.let { source ->
            videoCapturer.initialize(
                surfaceTextureHelper,
                context,
                source.capturerObserver
            )
            videoCapturer.startCapture(CAPTURE_WIDTH, CAPTURE_HEIGHT, CAPTURE_FPS)
            localVideoTrack = peerConnectionFactory.createVideoTrack("video0", source)
            localVideoTrack?.setEnabled(true)
            localVideoTrack?.let { track ->
                val sender = pc.addTrack(track)
                configureVideoSender(sender)
            }
        }
    }

    private fun configureVideoSender(sender: RtpSender?) {
        if (sender == null) return
        val params = sender.parameters ?: return
        params.degradationPreference = RtpParameters.DegradationPreference.DISABLED
        sender.parameters = params
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

    private suspend fun createVisionSession(offerSdp: String): String =
        withContext(Dispatchers.IO) {
            val mediaType = "application/json".toMediaType()
            val body = JSONObject()
                .put("offer_sdp", offerSdp)
                .toString()
                .toRequestBody(mediaType)
            val request = Request.Builder()
                .url(buildVisionSessionUrl())
                .post(body)
                .build()

            okHttp.newCall(request).execute().use { response ->
                val responseBody = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val msg = "Vision session request failed: HTTP ${response.code} ${response.message}"
                    Log.e(TAG, "$msg body=$responseBody")
                    throw IllegalStateException(msg)
                }
                val json = JSONObject(responseBody)
                normalizeSdp(json.optString("answer_sdp", ""))
            }
        }

    private fun buildVisionSessionUrl(): String {
        val normalizedBaseUrl = backendBaseUrl.trim().trimEnd('/')
        if (!normalizedBaseUrl.startsWith("http://") && !normalizedBaseUrl.startsWith("https://")) {
            throw IllegalArgumentException("BACKEND_BASE_URL must start with http:// or https://")
        }
        return "$normalizedBaseUrl/session/$sessionId/vision"
    }

    private fun normalizeSdp(raw: String): String {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return ""

        val text = trimmed
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\r\n", "\n")
            .replace('\r', '\n')

        val lines = text
            .split('\n')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
        if (lines.isEmpty()) return ""

        return lines.joinToString("\r\n", postfix = "\r\n")
    }

    private suspend fun createOffer(pc: PeerConnection): SessionDescription =
        suspendCancellableCoroutine { cont ->
            pc.createOffer(object : org.webrtc.SdpObserver {
                override fun onCreateSuccess(desc: SessionDescription?) {
                    if (desc != null && !cont.isCompleted) {
                        cont.resume(desc)
                    }
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
                    if (!cont.isCompleted) {
                        cont.resume(Unit)
                    }
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
                    if (!cont.isCompleted) {
                        cont.resume(Unit)
                    }
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
            deferred.complete(Unit)
            return
        }
        deferred.await()
        iceGatheringDeferred = null
    }
}
