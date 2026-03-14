package com.example.rokidovershoot

import android.content.Context
import android.media.AudioAttributes
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
import org.webrtc.audio.JavaAudioDeviceModule
import java.nio.charset.Charset
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class OpenAIRealtimeClient(
    private val context: Context,
    private val backendBaseUrl: String,
    private val sessionId: String,
    private val listener: Listener
) {

    interface Listener {
        fun onTranscriptDelta(itemId: String, delta: String)
        fun onTranscriptDone(itemId: String, transcript: String)
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
    private val transcriptLock = Any()
    private val ignoredTranscriptItemIds = HashSet<String>()

    private val audioDeviceModule by lazy {
        JavaAudioDeviceModule.builder(context)
            .setUseHardwareAcousticEchoCanceler(false)
            .setUseHardwareNoiseSuppressor(false)
            .setUseStereoInput(false)
            .setUseStereoOutput(false)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .createAudioDeviceModule().apply {
                setSpeakerMute(false)
            }
    }

    private val peerConnectionFactory: PeerConnectionFactory by lazy {
        createPeerConnectionFactory()
    }

    private var peerConnection: PeerConnection? = null
    private var dataChannel: DataChannel? = null
    private var iceGatheringDeferred: CompletableDeferred<Unit>? = null
    private var activeTranscriptItemId: String? = null
    private var speechEpoch: Int = 0

    private val mediaConstraints = MediaConstraints().apply {
        mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "true"))
        mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "false"))
    }

    fun setSpeechEpoch(epoch: Int) {
        if (epoch != speechEpoch) {
            synchronized(transcriptLock) {
                speechEpoch = epoch
                activeTranscriptItemId?.let { ignoredTranscriptItemIds.add(it) }
                activeTranscriptItemId = null
            }
        }
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
                Log.e(TAG, "Failed to start realtime session", t)
                listener.onError("Failed to start realtime session", t)
                stopInternal()
            }
        }
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
            true,
            true
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

        setupDataChannel(pc)

        val offer = createOffer(pc)
        setLocalDescription(pc, offer)
        waitForIceGatheringComplete(pc)

        val localSdp = pc.localDescription?.description ?: error("LocalDescription is null")
        val answerSdp = createRealtimeSession(localSdp)
        val answer = SessionDescription(SessionDescription.Type.ANSWER, answerSdp)
        setRemoteDescription(pc, answer)
    }

    private suspend fun stopInternal() = withContext(Dispatchers.Default) {
        dataChannel?.close()
        dataChannel = null

        peerConnection?.close()
        peerConnection?.dispose()
        peerConnection = null
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

    private fun setupDataChannel(pc: PeerConnection) {
        val dc = pc.createDataChannel(DATA_CHANNEL_LABEL, DataChannel.Init())
        dataChannel = dc

        dc.registerObserver(object : DataChannel.Observer {
            override fun onBufferedAmountChange(previousAmount: Long) {}

            override fun onStateChange() {
                Log.d(TAG, "DataChannel state: ${dc.state()}")
            }

            override fun onMessage(buffer: DataChannel.Buffer) {
                if (buffer.binary) {
                    return
                }
                val data = ByteArray(buffer.data.remaining())
                buffer.data.get(data)
                handleServerEvent(String(data, Charset.forName("UTF-8")))
            }
        })
    }

    private fun handleServerEvent(jsonText: String) {
        val json = try {
            JSONObject(jsonText)
        } catch (_: Throwable) {
            return
        }
        if (shouldIgnoreEvent(json)) return

        when (json.optString("type")) {
            "response.output_audio_transcript.delta" -> {
                val itemId = json.optString("item_id", "")
                val delta = json.optString("delta", "")
                if (itemId.isNotBlank() && delta.isNotEmpty() && shouldAcceptItem(itemId)) {
                    listener.onTranscriptDelta(itemId, delta)
                }
            }

            "response.output_audio_transcript.done" -> {
                val itemId = json.optString("item_id", "")
                val transcript = json.optString("transcript", "")
                if (itemId.isNotBlank() && shouldAcceptItem(itemId)) {
                    listener.onTranscriptDone(itemId, transcript)
                }
            }
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

    private fun shouldAcceptItem(itemId: String): Boolean {
        synchronized(transcriptLock) {
            if (ignoredTranscriptItemIds.contains(itemId)) {
                return false
            }

            val current = activeTranscriptItemId
            if (current == null) {
                activeTranscriptItemId = itemId
                return true
            }

            return current == itemId
        }
    }

    private suspend fun createRealtimeSession(offerSdp: String): String =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url(buildRealtimeSessionUrl())
                .post(offerSdp.toRequestBody("application/sdp".toMediaType()))
                .build()

            okHttp.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    val errorBody = response.body?.string()
                    val msg = "Realtime session request failed: HTTP ${response.code} ${response.message}"
                    Log.e(TAG, "$msg body=$errorBody")
                    throw IllegalStateException(msg)
                }
                normalizeSdp(response.body?.string().orEmpty())
            }
        }

    private fun buildRealtimeSessionUrl(): String {
        val normalizedBaseUrl = backendBaseUrl.trim().trimEnd('/')
        if (!normalizedBaseUrl.startsWith("http://") && !normalizedBaseUrl.startsWith("https://")) {
            throw IllegalArgumentException("BACKEND_BASE_URL must start with http:// or https://")
        }
        return "$normalizedBaseUrl/session/$sessionId/realtime"
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
