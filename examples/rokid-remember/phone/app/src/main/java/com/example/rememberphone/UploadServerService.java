package com.example.rememberphone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

import java.io.IOException;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.Enumeration;
import java.util.concurrent.atomic.AtomicBoolean;

public class UploadServerService extends Service {
    private static final String CHANNEL_ID = "remember-phone-upload-server";
    private static final int NOTIFICATION_ID = 2001;
    private static final String ACTION_START = "com.example.rememberphone.action.START";
    private static final String ACTION_STOP = "com.example.rememberphone.action.STOP";

    public static final int SERVER_PORT = 8000;

    private static final AtomicBoolean RUNNING = new AtomicBoolean(false);
    private static volatile String lastError;

    @Nullable
    private UploadHttpServer uploadHttpServer;

    public static Intent newStartIntent(Context context) {
        Intent intent = new Intent(context, UploadServerService.class);
        intent.setAction(ACTION_START);
        return intent;
    }

    public static Intent newStopIntent(Context context) {
        Intent intent = new Intent(context, UploadServerService.class);
        intent.setAction(ACTION_STOP);
        return intent;
    }

    public static boolean isRunning() {
        return RUNNING.get();
    }

    @Nullable
    public static String getLastError() {
        return lastError;
    }

    public static String getBestServerUrl() {
        return "http://" + resolveLocalIpv4Address() + ":" + SERVER_PORT;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ACTION_START : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            stopSelf();
            return START_NOT_STICKY;
        }

        startForeground(NOTIFICATION_ID, buildNotification());
        if (uploadHttpServer == null) {
            uploadHttpServer = new UploadHttpServer(this, SERVER_PORT);
            try {
                uploadHttpServer.start();
                RUNNING.set(true);
                lastError = null;
            } catch (IOException e) {
                RUNNING.set(false);
                lastError = "Failed to start server: " + e.getMessage();
                stopSelf();
            }
        }

        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (uploadHttpServer != null) {
            uploadHttpServer.stop();
            uploadHttpServer = null;
        }
        RUNNING.set(false);
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private Notification buildNotification() {
        Intent activityIntent = new Intent(this, MainActivity.class);
        int pendingIntentFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            pendingIntentFlags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent contentIntent =
                PendingIntent.getActivity(this, 0, activityIntent, pendingIntentFlags);

        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(getString(R.string.notification_title))
                .setContentText(getString(R.string.notification_text, getBestServerUrl()))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setContentIntent(contentIntent)
                .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }

        NotificationManager notificationManager =
                (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (notificationManager == null) {
            return;
        }

        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notification_channel_name),
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription(getString(R.string.notification_channel_description));
        notificationManager.createNotificationChannel(channel);
    }

    private static String resolveLocalIpv4Address() {
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces != null && interfaces.hasMoreElements()) {
                NetworkInterface networkInterface = interfaces.nextElement();
                if (!networkInterface.isUp() || networkInterface.isLoopback()) {
                    continue;
                }

                Enumeration<InetAddress> addresses = networkInterface.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    InetAddress address = addresses.nextElement();
                    if (address instanceof Inet4Address && !address.isLoopbackAddress()) {
                        return address.getHostAddress();
                    }
                }
            }
        } catch (Exception ignored) {
            // Fallback below.
        }
        return "0.0.0.0";
    }
}
