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

    private val itemsById = mutableMapOf<String, UiItem>()
    private val orderedIds = mutableListOf<String>()
    private val pendingText = mutableMapOf<String, String>()
    private val waitingForPrev = mutableMapOf<String, MutableSet<String>>()
    private var localSystemCounter = 0
    private var realtimeClient: OpenAIRealtimeClient? = null

    companion object {
        private const val REQ_PERMISSIONS = 1001
    }

    private val sessionUrl: String = BuildConfig.SESSION_URL

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.tvTitle.text = "Assembly Assistant"
        setStatus("Requesting mic/camera...")

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
            sessionUrl = sessionUrl,
            listener = this
        ).also { it.start() }
    }

    private fun stopRealtime() {
        realtimeClient?.release()
        realtimeClient = null
        setStatus("Stopped")
    }

    override fun onConversationItemAdded(
        itemId: String,
        role: String,
        status: String,
        previousItemId: String?
    ) {
        runOnUiThread {
            upsertItem(itemId, role, status, previousItemId)
        }
    }

    override fun onConversationItemDone(
        itemId: String,
        role: String,
        status: String,
        previousItemId: String?
    ) {
        runOnUiThread {
            upsertItem(itemId, role, status, previousItemId)
        }
    }

    override fun onUserTranscript(itemId: String, transcript: String) {
        runOnUiThread {
            attachTranscript(itemId, transcript)
            setStatus("Heard you")
        }
    }

    override fun onAssistantTranscriptFinal(itemId: String, transcript: String) {
        runOnUiThread {
            attachTranscript(itemId, transcript)
            setStatus("Assistant done")
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

    private fun upsertItem(
        itemId: String,
        role: String,
        status: String,
        previousItemId: String?
    ) {
        val itemRole = parseRole(role)
        val itemStatus = parseStatus(status)
        val existing = itemsById[itemId]
        val resolvedPrevId = if (previousItemId == null && existing != null) {
            existing.prevId
        } else {
            previousItemId
        }
        val uiItem = existing ?: UiItem(
            id = itemId,
            role = itemRole,
            status = itemStatus,
            prevId = resolvedPrevId,
            text = ""
        )
        uiItem.role = itemRole
        uiItem.status = itemStatus
        uiItem.prevId = resolvedPrevId
        itemsById[itemId] = uiItem
        if (existing == null || previousItemId != null) {
            upsertOrder(itemId, resolvedPrevId)
        }
        applyPendingText(itemId)
        renderConversation()
    }

    private fun attachTranscript(itemId: String, transcript: String) {
        val item = itemsById[itemId]
        if (item != null) {
            item.text = transcript
            renderConversation()
        } else {
            pendingText[itemId] = transcript
        }
    }

    private fun applyPendingText(itemId: String) {
        val pending = pendingText.remove(itemId) ?: return
        val item = itemsById[itemId] ?: return
        item.text = pending
    }

    private fun upsertOrder(itemId: String, previousItemId: String?) {
        orderedIds.remove(itemId)
        if (previousItemId == null) {
            orderedIds.add(0, itemId)
        } else {
            val prevIndex = orderedIds.indexOf(previousItemId)
            if (prevIndex >= 0) {
                orderedIds.add(prevIndex + 1, itemId)
            } else {
                val waiters = waitingForPrev.getOrPut(previousItemId) { mutableSetOf() }
                waiters.add(itemId)
                orderedIds.add(itemId)
            }
        }

        val waiters = waitingForPrev.remove(itemId) ?: return
        for (waiter in waiters) {
            val waiterItem = itemsById[waiter] ?: continue
            upsertOrder(waiter, waiterItem.prevId)
        }
    }

    private fun appendSystemMessage(msg: String) {
        val id = "local-system-${localSystemCounter++}"
        val item = UiItem(
            id = id,
            role = MessageRole.SYSTEM,
            status = ItemStatus.COMPLETED,
            prevId = null,
            text = msg
        )
        itemsById[id] = item
        orderedIds.add(id)
        renderConversation()
    }

    private fun renderConversation() {
        val builder = SpannableStringBuilder()

        orderedIds
            .mapNotNull { itemsById[it] }
            .filter { it.text.isNotBlank() }
            .forEach { message ->
            if (builder.isNotEmpty()) builder.append("\n")

            val prefix = when (message.role) {
                MessageRole.USER -> "User:"
                MessageRole.ASSISTANT -> "Assistant:"
                MessageRole.SYSTEM -> "[System]"
                MessageRole.TOOL -> "Tool:"
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
            builder.append(message.text)
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

    private fun parseRole(role: String): MessageRole {
        return when (role.lowercase()) {
            "user" -> MessageRole.USER
            "assistant" -> MessageRole.ASSISTANT
            "system" -> MessageRole.SYSTEM
            "tool" -> MessageRole.TOOL
            else -> MessageRole.SYSTEM
        }
    }

    private fun parseStatus(status: String): ItemStatus {
        return when (status.lowercase()) {
            "in_progress" -> ItemStatus.IN_PROGRESS
            "completed" -> ItemStatus.COMPLETED
            "cancelled" -> ItemStatus.CANCELLED
            "incomplete" -> ItemStatus.INCOMPLETE
            else -> ItemStatus.UNKNOWN
        }
    }

    private data class UiItem(
        val id: String,
        var role: MessageRole,
        var status: ItemStatus,
        var prevId: String?,
        var text: String
    )

    private enum class MessageRole {
        USER,
        ASSISTANT,
        SYSTEM,
        TOOL
    }

    private enum class ItemStatus {
        IN_PROGRESS,
        COMPLETED,
        CANCELLED,
        INCOMPLETE,
        UNKNOWN
    }
}
