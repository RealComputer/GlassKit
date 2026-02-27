package com.example.rokidrfdetr

enum class RecorderMode(val wireValue: String, val extension: String) {
    VIDEO("video", "mp4"),
    AUDIO("audio", "m4a");

    companion object {
        fun fromWireValue(raw: String?): RecorderMode? {
            if (raw == null) return null
            return entries.firstOrNull { it.wireValue == raw.lowercase() }
        }
    }
}
