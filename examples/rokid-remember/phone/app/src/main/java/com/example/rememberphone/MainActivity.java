package com.example.rememberphone;

import android.Manifest;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.TextView;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;

import java.io.File;

public class MainActivity extends AppCompatActivity {
    private boolean pendingStartAfterPermission;

    private final Handler statusHandler = new Handler(Looper.getMainLooper());
    private final Runnable statusTicker = new Runnable() {
        @Override
        public void run() {
            updateStatus();
            statusHandler.postDelayed(this, 1_000L);
        }
    };

    private final ActivityResultLauncher<String> notificationPermissionLauncher =
            registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> updateStatus());
    private final ActivityResultLauncher<String> legacyStoragePermissionLauncher =
            registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> {
                if (granted && pendingStartAfterPermission && canStartServerNow()) {
                    pendingStartAfterPermission = false;
                    startServer();
                } else if (!granted) {
                    pendingStartAfterPermission = false;
                }
                updateStatus();
            });

    private TextView statusView;
    private TextView urlView;
    private TextView storagePathView;
    private TextView lastErrorView;
    private Button startButton;
    private Button stopButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        statusView = findViewById(R.id.serverStatus);
        urlView = findViewById(R.id.serverUrl);
        storagePathView = findViewById(R.id.storagePath);
        lastErrorView = findViewById(R.id.lastError);
        startButton = findViewById(R.id.startButton);
        stopButton = findViewById(R.id.stopButton);

        startButton.setOnClickListener(view -> {
            if (!canStartServerNow()) {
                pendingStartAfterPermission = true;
                maybeRequestRuntimePermissions();
                updateStatus();
                return;
            }
            startServer();
        });

        stopButton.setOnClickListener(view -> {
            stopService(UploadServerService.newStopIntent(this));
            updateStatus();
        });

        maybeRequestRuntimePermissions();
        updateStatus();
    }

    @Override
    protected void onResume() {
        super.onResume();
        statusHandler.post(statusTicker);
    }

    @Override
    protected void onPause() {
        super.onPause();
        statusHandler.removeCallbacks(statusTicker);
    }

    private void maybeRequestRuntimePermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS);
        }

        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
                && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            legacyStoragePermissionLauncher.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE);
        }
    }

    private boolean canStartServerNow() {
        return Build.VERSION.SDK_INT > Build.VERSION_CODES.P
                || checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    private void startServer() {
        ContextCompat.startForegroundService(this, UploadServerService.newStartIntent(this));
        updateStatus();
    }

    private void updateStatus() {
        boolean running = UploadServerService.isRunning();
        statusView.setText(running ? R.string.server_running : R.string.server_stopped);
        startButton.setEnabled(!running);
        stopButton.setEnabled(running);

        urlView.setText(getString(R.string.server_url_value, UploadServerService.getBestServerUrl()));
        storagePathView.setText(getString(R.string.storage_path_value, getStorageDisplayPath()));

        String lastError = UploadServerService.getLastError();
        if (!canStartServerNow()) {
            lastErrorView.setText(R.string.last_error_storage_permission);
        } else if (lastError == null || lastError.isBlank()) {
            lastErrorView.setText(R.string.last_error_none);
        } else {
            lastErrorView.setText(getString(R.string.last_error_value, lastError));
        }
    }

    @SuppressWarnings("deprecation")
    private String getStorageDisplayPath() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            return "Downloads/RokidRemember";
        }

        File dir = new File(
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                "RokidRemember"
        );
        return dir.getAbsolutePath();
    }
}
