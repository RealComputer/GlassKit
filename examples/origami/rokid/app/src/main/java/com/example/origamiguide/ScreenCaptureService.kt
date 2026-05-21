package com.example.origamiguide

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import java.util.concurrent.CopyOnWriteArrayList

class ScreenCaptureService : Service() {
    private var startedForeground = false

    override fun onCreate() {
        super.onCreate()
        ensureNotificationChannel()
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(getString(R.string.app_name))
            .setContentText("Sharing HUD for demo")
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        startedForeground = true
        markForegroundReady()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (startedForeground) {
            markForegroundReady()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        foregroundReady = false
        readinessListeners.clear()
        super.onDestroy()
    }

    private fun ensureNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Origami guide capture",
            NotificationManager.IMPORTANCE_LOW
        )
        manager.createNotificationChannel(channel)
    }

    companion object {
        private const val CHANNEL_ID = "origami_screen_capture"
        private const val NOTIFICATION_ID = 2001
        private val readinessListeners = CopyOnWriteArrayList<() -> Unit>()

        @Volatile
        private var foregroundReady = false

        fun resetForegroundReady() {
            foregroundReady = false
            readinessListeners.clear()
        }

        fun addForegroundReadyListener(listener: () -> Unit): Boolean {
            if (foregroundReady) {
                return true
            }
            readinessListeners.add(listener)
            if (foregroundReady && readinessListeners.remove(listener)) {
                return true
            }
            return false
        }

        fun removeForegroundReadyListener(listener: () -> Unit) {
            readinessListeners.remove(listener)
        }

        private fun markForegroundReady() {
            foregroundReady = true
            val listeners = readinessListeners.toList()
            readinessListeners.clear()
            listeners.forEach { it.invoke() }
        }
    }
}
