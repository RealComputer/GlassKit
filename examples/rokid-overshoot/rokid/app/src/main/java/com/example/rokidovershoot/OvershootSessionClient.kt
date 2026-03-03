package com.example.rokidovershoot

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
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
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
    private val listener: Listener
) {

    interface Listener {
        fun onConnectionStateChanged(state: PeerConnection.IceConnectionState)
        fun onResultText(text: String)
        fun onStatus(message: String)
        fun onError(message: String, throwable: Throwable? = null)
        fun onSessionStopped()
    }

    companion object {
        private const val TAG = "OvershootSessionClient"
        private const val ICE_GATHERING_TIMEOUT_MS = 15_000L
        private const val OVERSHOOT_TURN_USERNAME = "overshoot"
        private const val OVERSHOOT_TURN_CREDENTIAL = "overshoot"
        private const val SESSION_COLLECTION_PATH = "/vision/session"
    }

    private data class SessionCreateResponse(
        val sessionId: String,
        val answerSdp: String
    )

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

    private var eventsWebSocket: WebSocket? = null
    private var currentSessionId: String? = null
    private var stopping = false
    private var hasNotifiedStopped = false

    private var iceGatheringDeferred: CompletableDeferred<Unit>? = null

    private val sessionCollectionUrl: String by lazy { buildSessionCollectionUrl() }

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
            stopping = false
            hasNotifiedStopped = false

            try {
                startInternal()
            } catch (t: Throwable) {
                Log.e(TAG, "Failed to start session", t)
                listener.onError("Failed to start session", t)
                stopInternal(notifyStopped = true)
            }
        }
    }

    fun stop() {
        scope.launch {
            stopInternal(notifyStopped = true)
        }
    }

    fun release() {
        runBlocking { stopInternal(notifyStopped = true) }
        scope.cancel()
        peerConnectionFactory.dispose()
        eglBase.release()
    }

    private suspend fun startInternal() = withContext(Dispatchers.Default) {
        listener.onStatus("Preparing camera")

        val pc = createPeerConnection()
        peerConnection = pc

        createAndAddVideoTrack(pc)

        listener.onStatus("Creating offer")
        val offer = createOffer(pc)
        setLocalDescription(pc, offer)
        waitForIceGatheringComplete(pc)

        val localSdp = pc.localDescription?.description
            ?: error("LocalDescription is null")

        listener.onStatus("Creating Overshoot stream")
        val createResponse = createSession(localSdp)
        currentSessionId = createResponse.sessionId

        val answer = SessionDescription(SessionDescription.Type.ANSWER, createResponse.answerSdp)
        setRemoteDescription(pc, answer)

        connectEventsWebSocket(createResponse.sessionId)

        Log.d(TAG, "WebRTC negotiation complete")
        listener.onStatus("Streaming")
    }

    private suspend fun stopInternal(notifyStopped: Boolean) = withContext(Dispatchers.Default) {
        stopping = true

        eventsWebSocket?.close(1000, "client stop")
        eventsWebSocket = null

        currentSessionId?.let { sessionId ->
            try {
                stopSession(sessionId)
            } catch (t: Throwable) {
                Log.w(TAG, "Failed to stop backend session $sessionId", t)
            }
        }
        currentSessionId = null

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

        if (notifyStopped) {
            notifySessionStopped()
        }

        Log.d(TAG, "Stopped session resources")
    }

    private fun notifySessionStopped() {
        if (hasNotifiedStopped) {
            return
        }
        hasNotifiedStopped = true
        listener.onSessionStopped()
    }

    private fun connectEventsWebSocket(sessionId: String) {
        val wsUrl = buildEventsWsUrl(sessionId)
        val request = Request.Builder()
            .url(wsUrl)
            .build()

        eventsWebSocket = okHttp.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                listener.onStatus("Receiving results")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val payload = JSONObject(text)
                    when (payload.optString("type")) {
                        "result" -> {
                            val resultText = payload.optString("text", "").trim()
                            if (resultText.isNotEmpty()) {
                                listener.onResultText(resultText)
                            }
                        }

                        "error" -> {
                            val errorMessage = payload.optString("message", "Unknown session error")
                            listener.onError(errorMessage)
                        }
                    }
                } catch (t: Throwable) {
                    Log.e(TAG, "Failed to parse websocket message: $text", t)
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (!stopping) {
                    listener.onError("Events websocket closed: $code $reason")
                    scope.launch {
                        stopInternal(notifyStopped = true)
                    }
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (!stopping) {
                    Log.e(TAG, "Events websocket failed", t)
                    listener.onError("Events websocket failed", t)
                    scope.launch {
                        stopInternal(notifyStopped = true)
                    }
                }
            }
        })
    }

    private fun buildEventsWsUrl(sessionId: String): String {
        val eventsHttpUrl = "${sessionCollectionUrl.trimEnd('/')}/$sessionId/events"
        return when {
            eventsHttpUrl.startsWith("https://") -> {
                eventsHttpUrl.replaceFirst("https://", "wss://")
            }

            eventsHttpUrl.startsWith("http://") -> {
                eventsHttpUrl.replaceFirst("http://", "ws://")
            }

            else -> {
                throw IllegalArgumentException("BACKEND_BASE_URL must start with http:// or https://")
            }
        }
    }

    private fun buildSessionCollectionUrl(): String {
        val normalizedBaseUrl = backendBaseUrl.trim().trimEnd('/')
        if (!normalizedBaseUrl.startsWith("http://") && !normalizedBaseUrl.startsWith("https://")) {
            throw IllegalArgumentException("BACKEND_BASE_URL must start with http:// or https://")
        }

        return "$normalizedBaseUrl$SESSION_COLLECTION_PATH"
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
            override fun onSignalingChange(newState: PeerConnection.SignalingState) {
                Log.d(TAG, "Signaling state: $newState")
            }

            override fun onIceConnectionChange(newState: PeerConnection.IceConnectionState) {
                Log.d(TAG, "ICE connection state: $newState")
                listener.onConnectionStateChanged(newState)
            }

            override fun onIceConnectionReceivingChange(receiving: Boolean) {
                Log.d(TAG, "ICE receiving: $receiving")
            }

            override fun onIceGatheringChange(newState: PeerConnection.IceGatheringState) {
                Log.d(TAG, "ICE gathering state: $newState")
                if (newState == PeerConnection.IceGatheringState.COMPLETE) {
                    iceGatheringDeferred?.complete(Unit)
                }
            }

            override fun onIceCandidate(candidate: IceCandidate) {
                Log.d(TAG, "ICE candidate: $candidate")
            }

            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) {
                Log.d(TAG, "ICE candidates removed: ${candidates.size}")
            }

            override fun onAddStream(stream: MediaStream) {
                Log.d(TAG, "Remote stream added: $stream")
            }

            override fun onRemoveStream(stream: MediaStream) {
                Log.d(TAG, "Remote stream removed: $stream")
            }

            override fun onDataChannel(dc: org.webrtc.DataChannel) {
                Log.d(TAG, "Ignoring incoming data channel: ${dc.label()}")
            }

            override fun onRenegotiationNeeded() {
                Log.d(TAG, "Renegotiation needed")
            }

            override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<out MediaStream>) {
                when (val track = receiver.track()) {
                    is VideoTrack -> {
                        track.setEnabled(true)
                        Log.d(TAG, "Remote video track added")
                    }
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
        if (videoCapturer == null) {
            throw IllegalStateException("No camera capturer available")
        }
        localVideoCapturer = videoCapturer

        surfaceTextureHelper = SurfaceTextureHelper.create(
            "OvershootCaptureThread",
            eglBase.eglBaseContext
        )

        localVideoSource = peerConnectionFactory.createVideoSource(videoCapturer.isScreencast).apply {
            adaptOutputFormat(1024, 768, 5)
        }

        localVideoSource?.let { source ->
            videoCapturer.initialize(
                surfaceTextureHelper,
                context,
                source.capturerObserver
            )
            videoCapturer.startCapture(1024, 768, 5)

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

        for (name in deviceNames) {
            enumerator.createCapturer(name, null)?.let { capturer ->
                Log.d(TAG, "Using camera: $name")
                return capturer
            }
        }

        Log.e(TAG, "No camera found")
        return null
    }

    private suspend fun createSession(offerSdp: String): SessionCreateResponse =
        withContext(Dispatchers.IO) {
            val mediaType = "application/json".toMediaType()
            val bodyJson = JSONObject()
                .put("offer_sdp", offerSdp)
                .toString()
            val body = bodyJson.toRequestBody(mediaType)

            val request = Request.Builder()
                .url(sessionCollectionUrl)
                .post(body)
                .build()

            okHttp.newCall(request).execute().use { response ->
                val responseBody = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val msg = "Session request failed: HTTP ${response.code} ${response.message}"
                    Log.e(TAG, "$msg body=$responseBody")
                    throw IllegalStateException(msg)
                }

                val json = JSONObject(responseBody)
                val sessionId = json.optString("session_id", "").trim()
                val answerSdp = json.optString("answer_sdp", "").trim()

                if (sessionId.isEmpty() || answerSdp.isEmpty()) {
                    throw IllegalStateException("Session response missing session_id or answer_sdp")
                }

                SessionCreateResponse(sessionId = sessionId, answerSdp = answerSdp)
            }
        }

    private suspend fun stopSession(sessionId: String) = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("${sessionCollectionUrl.trimEnd('/')}/$sessionId")
            .delete()
            .build()

        okHttp.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                Log.w(
                    TAG,
                    "Stop session failed: HTTP ${response.code} ${response.message} body=${response.body?.string()}"
                )
            }
        }
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

        val completed = withTimeoutOrNull(ICE_GATHERING_TIMEOUT_MS) {
            deferred.await()
            true
        } ?: false

        iceGatheringDeferred = null
        if (!completed) {
            Log.w(
                TAG,
                "Timed out waiting ${ICE_GATHERING_TIMEOUT_MS}ms for ICE gathering; proceeding with partial candidates"
            )
        }
    }
}
