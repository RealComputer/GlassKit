package com.example.rokidfeaturedemo

import android.util.Range
import android.util.Size
import android.view.Surface
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.camera2.interop.Camera2Interop
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.CameraSelector
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import android.hardware.camera2.CaptureRequest

@ExperimentalCamera2Interop
internal class CameraScreenController(
    private val activity: AppCompatActivity,
    panelView: View,
    private val hasCameraPermission: () -> Boolean
) : PanelScreenController(DemoScreen.CAMERA, panelView) {

    private data class CameraBindingAttempt(
        val useTargetResolution: Boolean,
        val useExactFps: Boolean
    )

    companion object {
        private val REQUESTED_CAMERA_SIZE = Size(1024, 768)
        private val REQUESTED_FPS = Range(5, 5)
    }

    private val cameraPreviewView: PreviewView = panelView.findViewById(R.id.cameraPreviewView)
    private val cameraStatusView: TextView = panelView.findViewById(R.id.cameraStatusView)

    private var cameraProvider: ProcessCameraProvider? = null
    private var isEntered = false

    init {
        cameraPreviewView.scaleType = PreviewView.ScaleType.FIT_CENTER
    }

    override fun handleAction(action: DemoAction): NavigationResult {
        return if (action == DemoAction.BACK) {
            NavigationResult.Open(DemoScreen.MENU)
        } else {
            NavigationResult.Stay
        }
    }

    override fun onEnter() {
        isEntered = true
        startCameraPreview()
    }

    override fun onExit() {
        isEntered = false
        stopCameraPreview()
    }

    override fun onHostStart() {
        if (isEntered) {
            startCameraPreview()
        }
    }

    override fun onHostStop() {
        stopCameraPreview()
    }

    override fun onPermissionsUpdated() {
        if (isEntered) {
            startCameraPreview()
        } else {
            cameraStatusView.text = if (hasCameraPermission()) {
                ""
            } else {
                activity.getString(R.string.camera_permission_needed)
            }
        }
    }

    private fun startCameraPreview() {
        if (!isEntered) return
        if (!hasCameraPermission()) {
            cameraStatusView.text = activity.getString(R.string.camera_permission_needed)
            return
        }

        cameraStatusView.text = activity.getString(R.string.camera_loading)
        val providerFuture = ProcessCameraProvider.getInstance(activity)
        providerFuture.addListener(
            {
                val provider = providerFuture.get()
                cameraProvider = provider
                if (!isEntered || activity.isFinishing || activity.isDestroyed) {
                    provider.unbindAll()
                    return@addListener
                }
                bindCameraWithFallback(provider)
            },
            ContextCompat.getMainExecutor(activity)
        )
    }

    private fun bindCameraWithFallback(provider: ProcessCameraProvider) {
        if (!isEntered || activity.isFinishing || activity.isDestroyed) {
            provider.unbindAll()
            return
        }

        val attempts = listOf(
            CameraBindingAttempt(useTargetResolution = true, useExactFps = true),
            CameraBindingAttempt(useTargetResolution = true, useExactFps = false),
            CameraBindingAttempt(useTargetResolution = false, useExactFps = false)
        )

        for (attempt in attempts) {
            if (!isEntered || activity.isFinishing || activity.isDestroyed) {
                provider.unbindAll()
                return
            }
            val success = runCatching {
                provider.unbindAll()
                val preview = buildPreview(attempt)
                preview.setSurfaceProvider(cameraPreviewView.surfaceProvider)
                provider.bindToLifecycle(activity, CameraSelector.DEFAULT_BACK_CAMERA, preview)
            }.isSuccess

            if (success) {
                cameraStatusView.text = if (attempt.useTargetResolution && attempt.useExactFps) {
                    "Rear camera preview active. 4:3 preview rotated for portrait at 5 fps."
                } else {
                    "Rear camera preview active. Device fallback configuration in use."
                }
                return
            }
        }

        cameraStatusView.text = activity.getString(R.string.camera_unavailable)
    }

    private fun buildPreview(attempt: CameraBindingAttempt): Preview {
        val builder = Preview.Builder()
        // PreviewView only applies the correct transform when the use case knows the
        // display rotation it should target. Rokid's camera stream is landscape in
        // sensor space, so we rotate it into the portrait HUD here.
        builder.setTargetRotation(cameraPreviewView.display?.rotation ?: Surface.ROTATION_0)
        if (attempt.useTargetResolution) {
            builder.setResolutionSelector(
                ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(
                            REQUESTED_CAMERA_SIZE,
                            ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER
                        )
                    )
                    .build()
            )
        }
        if (attempt.useExactFps) {
            Camera2Interop.Extender(builder).setCaptureRequestOption(
                CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,
                REQUESTED_FPS
            )
        }
        return builder.build()
    }

    private fun stopCameraPreview() {
        cameraProvider?.unbindAll()
        cameraProvider = null
    }
}
