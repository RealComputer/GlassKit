package com.example.rokidovershootopenairealtime

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject

class BackendControlClient(
    private val backendBaseUrl: String,
    private val listener: Listener
) {

    data class HudTask(
        val id: String,
        val text: String,
        val completed: Boolean
    )

    data class HudState(
        val screen: String,
        val phase: String,
        val recipeName: String?,
        val tasks: List<HudTask>,
        val activeTaskId: String?,
        val speechEpoch: Int
    )

    interface Listener {
        fun onSessionReady(sessionId: String)
        fun onHudState(state: HudState)
        fun onHudError(message: String)
        fun onControlClosed(message: String)
    }

    companion object {
        private const val SESSION_CONTROL_PATH = "/session/control"
    }

    private val okHttp = OkHttpClient()
    private var closed = false
    private var webSocket: WebSocket? = null

    fun connect() {
        if (webSocket != null) return

        closed = false
        val request = Request.Builder()
            .url(buildControlUrl())
            .build()
        webSocket = okHttp.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                this@BackendControlClient.webSocket = null
                if (!closed) {
                    listener.onControlClosed("Backend disconnected. Tap to reconnect.")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                this@BackendControlClient.webSocket = null
                if (!closed) {
                    listener.onControlClosed("Backend unavailable. Tap to reconnect.")
                }
            }
        })
    }

    fun close() {
        closed = true
        webSocket?.close(1000, "client close")
        webSocket = null
    }

    fun sendStart() {
        sendJson(JSONObject().put("type", "session.start"))
    }

    fun sendStop() {
        sendJson(JSONObject().put("type", "session.stop"))
    }

    fun sendDebugStep(direction: String) {
        sendJson(
            JSONObject()
                .put("type", "debug.step")
                .put("direction", direction)
        )
    }

    private fun sendJson(payload: JSONObject) {
        webSocket?.send(payload.toString())
    }

    private fun handleMessage(text: String) {
        val payload = try {
            JSONObject(text)
        } catch (_: Throwable) {
            return
        }

        when (payload.optString("type")) {
            "session.ready" -> {
                val sessionId = payload.optString("session_id", "")
                if (sessionId.isNotBlank()) {
                    listener.onSessionReady(sessionId)
                }
            }

            "hud.state" -> {
                listener.onHudState(parseHudState(payload))
            }

            "hud.error" -> {
                val message = payload.optString("message", "Something went wrong.")
                listener.onHudError(message)
            }
        }
    }

    private fun parseHudState(payload: JSONObject): HudState {
        val tasksJson = payload.optJSONArray("tasks") ?: JSONArray()
        val tasks = mutableListOf<HudTask>()
        for (index in 0 until tasksJson.length()) {
            val item = tasksJson.optJSONObject(index) ?: continue
            val id = item.optString("id", "")
            val text = item.optString("text", "")
            if (id.isBlank() || text.isBlank()) continue
            tasks += HudTask(
                id = id,
                text = text,
                completed = item.optBoolean("completed", false)
            )
        }

        val recipeName = payload.optString("recipe_name").takeIf { it.isNotBlank() }
        val activeTaskId = payload.optString("active_task_id").takeIf { it.isNotBlank() }
        return HudState(
            screen = payload.optString("screen", "start"),
            phase = payload.optString("phase", "WAITING_FOR_START"),
            recipeName = recipeName,
            tasks = tasks,
            activeTaskId = activeTaskId,
            speechEpoch = payload.optInt("speech_epoch", 0)
        )
    }

    private fun buildControlUrl(): String {
        val controlHttpUrl = "${backendBaseUrl.trim().trimEnd('/')}$SESSION_CONTROL_PATH"
        return when {
            controlHttpUrl.startsWith("https://") -> {
                controlHttpUrl.replaceFirst("https://", "wss://")
            }

            controlHttpUrl.startsWith("http://") -> {
                controlHttpUrl.replaceFirst("http://", "ws://")
            }

            else -> {
                throw IllegalArgumentException("BACKEND_BASE_URL must start with http:// or https://")
            }
        }
    }
}
