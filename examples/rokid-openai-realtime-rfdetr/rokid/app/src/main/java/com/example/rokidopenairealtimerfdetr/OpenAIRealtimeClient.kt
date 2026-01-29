package com.example.rokidopenairealtimerfdetr

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaRecorder
import android.os.Build
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
import org.webrtc.AudioSource
import org.webrtc.AudioTrack
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
import org.webrtc.RtpReceiver
import org.webrtc.SessionDescription
import org.webrtc.SurfaceTextureHelper
import org.webrtc.VideoCapturer
import org.webrtc.VideoSource
import org.webrtc.VideoTrack
import org.webrtc.audio.JavaAudioDeviceModule
import java.nio.charset.Charset
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Establishes a WebRTC session via the backend `/session` SDP broker, then streams
 * microphone audio + camera video directly to OpenAI Realtime; events land on the
 * "oai-events" data channel.
 */
class OpenAIRealtimeClient(
    private val context: Context,
    private val sessionUrl: String,
    private val listener: Listener
) {

    interface Listener {
        fun onConversationItemAdded(
            itemId: String,
            role: String,
            status: String,
            previousItemId: String?
        )
        fun onConversationItemDone(
            itemId: String,
            role: String,
            status: String,
            previousItemId: String?
        )
        fun onUserTranscript(itemId: String, transcript: String)
        fun onAssistantTranscriptFinal(itemId: String, transcript: String)
        fun onConnectionStateChanged(state: PeerConnection.IceConnectionState)
        fun onError(message: String, throwable: Throwable? = null)
    }

    companion object {
        private const val TAG = "OpenAIRealtimeClient"
        private const val DATA_CHANNEL_LABEL = "oai-events"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val okHttp = OkHttpClient()
    private val eglBase: EglBase = EglBase.create()
    private val seenEventIds = HashSet<String>()

    private val audioDeviceModule by lazy {
        JavaAudioDeviceModule.builder(context)
            // Keep capture mono; force lower, safer sample rate to avoid HAL crashes when playing remote audio.
            .setSampleRate(16_000)
            .setUseHardwareAcousticEchoCanceler(false)
            .setUseHardwareNoiseSuppressor(false)
            .setUseStereoInput(false)
            .setUseStereoOutput(false)
            // Use MEDIA routing instead of VOICE_COMMUNICATION to steer away from vendor VOIP path.
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioSource(MediaRecorder.AudioSource.MIC)
            .createAudioDeviceModule().apply {
                setMicrophoneMute(false)
                setSpeakerMute(false)
            }
    }

    private val peerConnectionFactory: PeerConnectionFactory by lazy {
        createPeerConnectionFactory()
    }

    private var peerConnection: PeerConnection? = null

    private var localAudioSource: AudioSource? = null
    private var localAudioTrack: AudioTrack? = null

    private var localVideoSource: VideoSource? = null
    private var localVideoTrack: VideoTrack? = null
    private var localVideoCapturer: VideoCapturer? = null
    private var surfaceTextureHelper: SurfaceTextureHelper? = null

    private var dataChannel: DataChannel? = null
    private var iceGatheringDeferred: CompletableDeferred<Unit>? = null

    private val mediaConstraints = MediaConstraints().apply {
        mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "true"))
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
                Log.e(TAG, "Failed to start session", t)
                listener.onError("Failed to start session", t)
                stopInternal()
            }
        }
    }

    fun stop() {
        scope.launch { stopInternal() }
    }

    fun release() {
        runBlocking { stopInternal() }
        scope.cancel()
        audioDeviceModule.release()
        peerConnectionFactory.dispose()
        eglBase.release()
    }

    private fun createPeerConnectionFactory(): PeerConnectionFactory {
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(context)
                .createInitializationOptions()
        )

        val encoderFactory = DefaultVideoEncoderFactory(
            eglBase.eglBaseContext,
            /* enableIntelVp8Encoder = */ true,
            /* enableH264HighProfile = */ true
        )
        val decoderFactory = DefaultVideoDecoderFactory(eglBase.eglBaseContext)

        return PeerConnectionFactory.builder()
            .setAudioDeviceModule(audioDeviceModule)
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .createPeerConnectionFactory()
    }

    private suspend fun startInternal() = withContext(Dispatchers.Default) {
        val pc = createPeerConnection()
        peerConnection = pc

        createAndAddMediaTracks(pc)
        setupDataChannel(pc)

        val offer = createOffer(pc)
        setLocalDescription(pc, offer)

        waitForIceGatheringComplete(pc)

        val localSdp = pc.localDescription ?: error("LocalDescription is null")
        val answerSdp = sendOfferAndGetAnswer(localSdp.description)

        val answer = SessionDescription(SessionDescription.Type.ANSWER, answerSdp)
        setRemoteDescription(pc, answer)

        Log.d(TAG, "WebRTC negotiation complete")
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

        localAudioTrack?.dispose()
        localAudioTrack = null
        localAudioSource?.dispose()
        localAudioSource = null

        dataChannel?.close()
        dataChannel = null

        peerConnection?.close()
        peerConnection?.dispose()
        peerConnection = null

        Log.d(TAG, "Stopped and cleaned up WebRTC resources")
    }

    private fun createPeerConnection(): PeerConnection {
        val iceServers = listOf(
            PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer()
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
                Log.d(TAG, "ICE connection receiving: $receiving")
            }

            override fun onIceGatheringChange(newState: PeerConnection.IceGatheringState) {
                Log.d(TAG, "ICE gathering state: $newState")
                if (newState == PeerConnection.IceGatheringState.COMPLETE) {
                    iceGatheringDeferred?.complete(Unit)
                }
            }

            override fun onIceCandidate(candidate: IceCandidate) {
                Log.d(TAG, "onIceCandidate: $candidate")
            }

            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) {
                Log.d(TAG, "onIceCandidatesRemoved: ${candidates.size}")
            }

            override fun onAddStream(stream: MediaStream) {
                Log.d(TAG, "onAddStream: $stream")
            }

            override fun onRemoveStream(stream: MediaStream) {
                Log.d(TAG, "onRemoveStream: $stream")
            }

            override fun onDataChannel(dc: DataChannel) {
                Log.d(TAG, "onDataChannel: ${dc.label()}")
            }

            override fun onRenegotiationNeeded() {
                Log.d(TAG, "onRenegotiationNeeded")
            }

            override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<out MediaStream>) {
                val track = receiver.track()
                when (track) {
                    is AudioTrack -> {
                        Log.d(TAG, "Remote audio track added")
                        track.setEnabled(true)
                    }

                    is VideoTrack -> {
                        Log.d(TAG, "Remote video track added (not rendered)")
                    }
                }
            }
        }) ?: error("Failed to create PeerConnection")
    }

    private fun createAndAddMediaTracks(pc: PeerConnection) {
        localAudioSource = peerConnectionFactory.createAudioSource(MediaConstraints())
        localAudioTrack = peerConnectionFactory.createAudioTrack("audio0", localAudioSource)
        localAudioTrack?.setEnabled(true)
        localAudioTrack?.let { pc.addTrack(it) }

        val videoCapturer = createCameraCapturer()
        if (videoCapturer == null) {
            Log.e(TAG, "No camera capturer available; skipping video")
            return
        }
        localVideoCapturer = videoCapturer

        surfaceTextureHelper = SurfaceTextureHelper.create(
            "CaptureThread",
            eglBase.eglBaseContext
        )

        localVideoSource = peerConnectionFactory.createVideoSource(videoCapturer.isScreencast).apply {
            adaptOutputFormat(
                720,
                1280,
                2
            )
        }
        localVideoSource?.let { source ->
            videoCapturer.initialize(
                surfaceTextureHelper,
                context,
                source.capturerObserver
            )
            videoCapturer.startCapture(720, 1280, 15) // supported value
            localVideoTrack = peerConnectionFactory.createVideoTrack("video0", source)
            localVideoTrack?.setEnabled(true)
            localVideoTrack?.let { track -> pc.addTrack(track) }
        }
    }

    private fun createCameraCapturer(): VideoCapturer? {
        val enumerator = Camera2Enumerator(context)
        val deviceNames = enumerator.deviceNames

        val preferred = selectPreferredCameraName(enumerator, deviceNames)
        if (preferred != null) {
            enumerator.createCapturer(preferred, null)?.let { capturer ->
                Log.d(TAG, "Using camera: $preferred")
                return capturer
            }
            Log.w(TAG, "Failed to open preferred camera $preferred, falling back")
        }

        for (name in deviceNames) {
            enumerator.createCapturer(name, null)?.let { capturer ->
                Log.d(TAG, "Using fallback camera: $name")
                return capturer
            }
        }

        Log.e(TAG, "No camera found")
        return null
    }

    /**
     * Prefer a back/outward camera when available; otherwise use the first device found.
     */
    private fun selectPreferredCameraName(
        enumerator: Camera2Enumerator,
        deviceNames: Array<String>
    ): String? {
        var fallback: String? = null
        for (name in deviceNames) {
            if (!enumerator.isFrontFacing(name)) {
                return name
            }
            if (fallback == null) fallback = name
        }
        return fallback
    }

    private fun setupDataChannel(pc: PeerConnection) {
        val init = DataChannel.Init()
        val dc = pc.createDataChannel(DATA_CHANNEL_LABEL, init)
        dataChannel = dc

        dc.registerObserver(object : DataChannel.Observer {
            override fun onBufferedAmountChange(previousAmount: Long) {}

            override fun onStateChange() {
                Log.d(TAG, "DataChannel state: ${dc.state()}")
            }

            override fun onMessage(buffer: DataChannel.Buffer) {
                if (buffer.binary) {
                    Log.w(TAG, "Ignoring binary message on $DATA_CHANNEL_LABEL")
                    return
                }
                val data = ByteArray(buffer.data.remaining())
                buffer.data.get(data)
                val jsonText = String(data, Charset.forName("UTF-8"))
                handleServerEvent(jsonText)
            }
        })
    }

    private fun handleServerEvent(jsonText: String) {
        try {
            val json = JSONObject(jsonText)
            if (shouldIgnoreEvent(json)) return
            when (val type = json.optString("type")) {
                "conversation.item.added",
                "conversation.item.done" -> {
                    val item = json.optJSONObject("item") ?: return
                    val itemId = item.optString("id")
                    if (itemId.isBlank()) return
                    val role = item.optString("role", "")
                    val status = item.optString("status", "")
                    val prevId = if (json.has("previous_item_id")) {
                        json.optString("previous_item_id").takeIf { it.isNotBlank() }
                    } else {
                        null
                    }
                    if (type == "conversation.item.added") {
                        listener.onConversationItemAdded(itemId, role, status, prevId)
                    } else {
                        listener.onConversationItemDone(itemId, role, status, prevId)
                    }
                }

                "conversation.item.input_audio_transcription.completed" -> {
                    val itemId = json.optString("item_id", "")
                    if (itemId.isNotEmpty()) {
                        val transcript = json.optString("transcript", "")
                        listener.onUserTranscript(itemId, transcript)
                    }
                }

                "response.output_audio_transcript.done" -> {
                    val itemId = json.optString("item_id", "")
                    if (itemId.isNotEmpty()) {
                        val transcript = json.optString("transcript", "")
                        listener.onAssistantTranscriptFinal(itemId, transcript)
                    }
                }

                else -> {
                    // Log.d(TAG, "Ignoring event type: $type")
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "Failed to parse server event: $jsonText", t)
        }
    }

    private fun shouldIgnoreEvent(json: JSONObject): Boolean {
        val eventId = json.optString("event_id", "")
        if (eventId.isBlank()) return false
        synchronized(seenEventIds) {
            if (seenEventIds.contains(eventId)) return true
            seenEventIds.add(eventId)
        }
        return false
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

    private suspend fun sendOfferAndGetAnswer(offerSdp: String): String =
        withContext(Dispatchers.IO) {
            val mediaType = "application/sdp".toMediaType()
            val body = offerSdp.toRequestBody(mediaType)

            val request = Request.Builder()
                .url(sessionUrl)
                .post(body)
                .build()

            okHttp.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    val errorBody = response.body?.string()
                    val msg = "Session request failed: HTTP ${response.code} ${response.message}"
                    Log.e(TAG, "$msg body=$errorBody")
                    throw IllegalStateException(msg)
                }
                response.body?.string() ?: throw IllegalStateException("Empty SDP answer")
            }
        }
}
