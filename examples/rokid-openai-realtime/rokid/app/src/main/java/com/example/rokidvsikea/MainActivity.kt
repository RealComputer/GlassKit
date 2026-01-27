package com.example.rokidvsikea

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Bundle
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.RelativeSizeSpan
import android.text.style.StyleSpan
import android.view.KeyEvent
import android.view.ViewTreeObserver
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.example.rokidvsikea.databinding.ActivityMainBinding
import org.webrtc.PeerConnection

class MainActivity : AppCompatActivity(), OpenAIRealtimeClient.Listener {

    private lateinit var binding: ActivityMainBinding

    private val conversation = mutableListOf<Message>()
    private val userBuffer = StringBuilder()
    private val assistantBuffer = StringBuilder()
    private var realtimeClient: OpenAIRealtimeClient? = null

    companion object {
        private const val REQ_PERMISSIONS = 1001
        private const val SESSION_URL = "http://192.168.68.51:3000/session" // TODO set to your backend
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.tvTitle.text = "Assembly Assistant"
        setStatus("Requesting mic/camera...")

        // Start with an empty user message so assistant replies can't get ahead in the UI order.
        ensureUserPlaceholder()

        setupAutoScroll(binding.tvConversation, binding.scrollView)
        ensurePermissions()
    }

    private fun ensurePermissions() {
        val needed = listOf(
            Manifest.permission.CAMERA,
            Manifest.permission.RECORD_AUDIO
        ).filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (needed.isEmpty()) {
            startRealtimeIfNeeded()
        } else {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), REQ_PERMISSIONS)
        }
    }

    private fun hasPermissions(): Boolean {
        val permissions = listOf(
            Manifest.permission.CAMERA,
            Manifest.permission.RECORD_AUDIO
        )
        return permissions.all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_PERMISSIONS) {
            if (grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
                startRealtimeIfNeeded()
            } else {
                setStatus("Camera/mic permission denied; app cannot stream.")
                appendSystemMessage("Camera/mic permission denied; streaming unavailable.")
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopRealtime()
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_DPAD_CENTER,
            KeyEvent.KEYCODE_ENTER -> {
                toggleRealtime()
                true
            }
            else -> super.onKeyUp(keyCode, event)
        }
    }

    private fun toggleRealtime() {
        if (realtimeClient == null) {
            appendSystemMessage("Starting voice link...")
            startRealtimeIfNeeded()
        } else {
            appendSystemMessage("Stopping voice link...")
            stopRealtime()
        }
    }

    private fun startRealtimeIfNeeded() {
        if (realtimeClient != null) return
        if (!hasPermissions()) {
            ensurePermissions()
            return
        }
        setStatus("Connecting...")
        // appendSystemMessage("Streaming mic + camera to assistant...")

        realtimeClient = OpenAIRealtimeClient(
            context = applicationContext,
            sessionUrl = SESSION_URL,
            listener = this
        ).also { it.start() }
    }

    private fun stopRealtime() {
        realtimeClient?.release()
        realtimeClient = null
        assistantBuffer.clear()
        setStatus("Stopped")
    }

    override fun onUserTranscript(transcript: String) {
        runOnUiThread {
            userBuffer.clear()
            userBuffer.append(transcript)
            upsertUserMessage(userBuffer.toString())
            setStatus("Heard you")
        }
    }

    override fun onUserTranscriptDelta(delta: String) {
        runOnUiThread {
            // Always write into the latest user message, even if an assistant line was already added.
            if (conversation.lastOrNull()?.role != MessageRole.USER) {
                ensureUserPlaceholder()
                userBuffer.clear()
            }
            userBuffer.append(delta)
            upsertUserMessage(userBuffer.toString())
            setStatus("Hearing you")
        }
    }

    override fun onAssistantTranscriptDelta(delta: String) {
        runOnUiThread {
            assistantBuffer.append(delta)
            val current = assistantBuffer.toString()
            upsertAssistantMessage(current)
            setStatus("Assistant speaking")
        }
    }

    override fun onAssistantTranscriptFinal(transcript: String) {
        runOnUiThread {
            assistantBuffer.clear()
            assistantBuffer.append(transcript)
            upsertAssistantMessage(transcript)
            setStatus("Assistant done")
            // Prepare a placeholder for the next user utterance so ordering stays User → Assistant.
            ensureUserPlaceholder()
        }
    }

    override fun onConnectionStateChanged(state: PeerConnection.IceConnectionState) {
        runOnUiThread {
            setStatus("Connection: $state")
            if (state == PeerConnection.IceConnectionState.FAILED ||
                state == PeerConnection.IceConnectionState.CLOSED ||
                state == PeerConnection.IceConnectionState.DISCONNECTED
            ) {
                appendSystemMessage("Link closed ($state). Tap to reconnect.")
                stopRealtime()
            }
        }
    }

    override fun onError(message: String, throwable: Throwable?) {
        runOnUiThread {
            appendSystemMessage("Error: $message")
            setStatus("Error: $message")
            stopRealtime()
        }
    }

    private fun addMessage(role: MessageRole, text: String) {
        conversation.add(Message(role, text))
        renderConversation()
    }

    private fun upsertAssistantMessage(text: String) {
        val lastIndex = conversation.lastIndex
        if (lastIndex >= 0 && conversation[lastIndex].role == MessageRole.ASSISTANT) {
            conversation[lastIndex] = conversation[lastIndex].copy(content = text)
        } else {
            conversation.add(Message(MessageRole.ASSISTANT, text))
        }
        renderConversation()
    }

    private fun upsertUserMessage(text: String) {
        val idx = conversation.indexOfLast { it.role == MessageRole.USER }
        if (idx >= 0) {
            conversation[idx] = conversation[idx].copy(content = text)
        } else {
            conversation.add(Message(MessageRole.USER, text))
        }
        renderConversation()
    }

    private fun ensureUserPlaceholder() {
        if (conversation.lastOrNull()?.role != MessageRole.USER) {
            conversation.add(Message(MessageRole.USER, ""))
            renderConversation()
        }
    }

    private fun appendSystemMessage(msg: String) {
        addMessage(MessageRole.SYSTEM, msg)
    }

    private fun renderConversation() {
        val builder = SpannableStringBuilder()

        conversation.forEach { message ->
            if (builder.isNotEmpty()) builder.append("\n")

            val prefix = when (message.role) {
                MessageRole.USER -> "User:"
                MessageRole.ASSISTANT -> "Assistant:"
                MessageRole.SYSTEM -> "[System]"
            }

            val start = builder.length
            builder.append(prefix)
            val end = builder.length

            if (message.role != MessageRole.SYSTEM && end > start) {
                builder.setSpan(
                    StyleSpan(Typeface.BOLD),
                    start,
                    end,
                    Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
                )
                builder.setSpan(
                    RelativeSizeSpan(1.2f),
                    start,
                    end,
                    Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
                )
            }

            builder.append("\n")
            val contentStart = builder.length
            builder.append(message.content)
            val contentEnd = builder.length
            // Only style non-empty content to avoid zero-length span errors.
            if (contentEnd > contentStart) {
                // Keep content size aligned with the role label for readability.
                builder.setSpan(
                    RelativeSizeSpan(1.2f),
                    contentStart,
                    contentEnd,
                    Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
                )
            }
        }

        binding.tvConversation.text = builder
    }

    private fun setStatus(text: String) {
        binding.tvStatus.text = text
    }

    private fun setupAutoScroll(textView: TextView, scrollView: android.widget.ScrollView) {
        textView.viewTreeObserver.addOnGlobalLayoutListener(
            object : ViewTreeObserver.OnGlobalLayoutListener {
                override fun onGlobalLayout() {
                    scrollView.post {
                        scrollView.fullScroll(android.view.View.FOCUS_DOWN)
                    }
                }
            }
        )
    }

    private data class Message(val role: MessageRole, val content: String)

    private enum class MessageRole {
        USER,
        ASSISTANT,
        SYSTEM
    }
}
