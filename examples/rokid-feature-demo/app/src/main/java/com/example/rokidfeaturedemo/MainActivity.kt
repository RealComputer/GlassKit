package com.example.rokidfeaturedemo

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.GestureDetector
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import kotlin.math.abs

@ExperimentalCamera2Interop
class MainActivity : AppCompatActivity() {

    companion object {
        private const val REQUEST_PERMISSIONS = 1001
        private const val SWIPE_DISTANCE_THRESHOLD_DP = 56f
    }

    private lateinit var breadcrumbView: TextView
    private lateinit var controlHelpView: TextView
    private lateinit var microphoneScreenController: MicrophoneScreenController
    private lateinit var screenControllers: Map<DemoScreen, ScreenController>

    private var currentScreen = DemoScreen.MENU
    private var voiceRecognizer: VoiceCommandRecognizer? = null
    private var swipeStartX = 0f
    private var swipeStartY = 0f
    private var isSwipeTracking = false
    private var swipeHandledByFling = false

    private val swipeDistanceThresholdPx by lazy {
        SWIPE_DISTANCE_THRESHOLD_DP * resources.displayMetrics.density
    }
    private val swipeDirectionSlopPx by lazy {
        ViewConfiguration.get(this).scaledTouchSlop * 4f
    }

    private val gestureDetector by lazy {
        GestureDetector(
            this,
            object : GestureDetector.SimpleOnGestureListener() {
                override fun onDown(e: MotionEvent): Boolean = true

                override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
                    handleAction(DemoAction.SELECT)
                    return true
                }

                override fun onDoubleTap(e: MotionEvent): Boolean {
                    handleAction(DemoAction.BACK)
                    return true
                }

                override fun onFling(
                    e1: MotionEvent?,
                    e2: MotionEvent,
                    velocityX: Float,
                    velocityY: Float
                ): Boolean {
                    val start = e1 ?: return false
                    val deltaX = e2.x - start.x
                    val deltaY = e2.y - start.y
                    if (!isHorizontalSwipe(deltaX, deltaY)) return false

                    swipeHandledByFling = true
                    if (deltaX > 0f) {
                        handleAction(DemoAction.NEXT)
                    } else {
                        handleAction(DemoAction.PREVIOUS)
                    }
                    return true
                }
            }
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)

        bindChromeViews()
        bindScreenControllers()
        microphoneScreenController.setVoiceStatus(initialVoiceStatus())
        renderUi()
        ensurePermissions()

        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    handleAction(DemoAction.BACK)
                }
            }
        )
    }

    override fun onStart() {
        super.onStart()
        if (hasRecordAudioPermission()) {
            startVoiceIfPossible()
        }
        currentScreenController().onHostStart()
    }

    override fun onStop() {
        currentScreenController().onHostStop()
        voiceRecognizer?.stop()
        super.onStop()
    }

    override fun onDestroy() {
        voiceRecognizer?.release()
        screenControllers.values.forEach { it.onDestroy() }
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onDestroy()
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        val handledByGestureDetector = gestureDetector.onTouchEvent(event)
        val handledBySwipeFallback = handleSwipeFallback(event)
        return handledByGestureDetector || handledBySwipeFallback || super.dispatchTouchEvent(event)
    }

    @SuppressLint("GestureBackNavigation")
    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_ENTER -> {
                handleAction(DemoAction.SELECT)
                true
            }

            KeyEvent.KEYCODE_BACK -> {
                onBackPressedDispatcher.onBackPressed()
                true
            }

            KeyEvent.KEYCODE_DPAD_DOWN -> {
                handleAction(DemoAction.NEXT)
                true
            }

            KeyEvent.KEYCODE_DPAD_UP -> {
                handleAction(DemoAction.PREVIOUS)
                true
            }

            else -> super.onKeyUp(keyCode, event)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQUEST_PERMISSIONS) return

        if (hasRecordAudioPermission()) {
            startVoiceIfPossible()
        } else {
            microphoneScreenController.setVoiceStatus(getString(R.string.voice_permission_denied))
        }
        screenControllers.values.forEach { it.onPermissionsUpdated() }
        renderUi()
    }

    private fun bindChromeViews() {
        breadcrumbView = findViewById(R.id.breadcrumbView)
        controlHelpView = findViewById(R.id.controlHelpView)
    }

    @ExperimentalCamera2Interop
    private fun bindScreenControllers() {
        val menuController = MenuScreenController(findViewById(R.id.menuPanel))
        val cameraController = CameraScreenController(
            activity = this,
            panelView = findViewById(R.id.cameraPanel),
            hasCameraPermission = ::hasCameraPermission
        )
        val audioController = AudioScreenController(findViewById(R.id.audioPanel))
        microphoneScreenController = MicrophoneScreenController(
            panelView = findViewById(R.id.micPanel),
            hasRecordAudioPermission = ::hasRecordAudioPermission,
            initialVoiceStatus = ::initialVoiceStatus
        )
        screenControllers = linkedMapOf(
            menuController.screen to menuController,
            cameraController.screen to cameraController,
            audioController.screen to audioController,
            microphoneScreenController.screen to microphoneScreenController
        )
    }

    private fun ensurePermissions() {
        val missing = buildList {
            if (!hasCameraPermission()) add(Manifest.permission.CAMERA)
            if (!hasRecordAudioPermission()) add(Manifest.permission.RECORD_AUDIO)
        }
        if (missing.isEmpty()) return
        ActivityCompat.requestPermissions(this, missing.toTypedArray(), REQUEST_PERMISSIONS)
    }

    private fun hasCameraPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.CAMERA
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasRecordAudioPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun handleSwipeFallback(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                swipeStartX = event.x
                swipeStartY = event.y
                isSwipeTracking = true
                swipeHandledByFling = false
            }

            MotionEvent.ACTION_CANCEL -> resetSwipeTracking()

            MotionEvent.ACTION_UP -> {
                if (!isSwipeTracking) return false

                val deltaX = event.x - swipeStartX
                val deltaY = event.y - swipeStartY
                val handledByFling = swipeHandledByFling
                resetSwipeTracking()

                if (handledByFling || !isHorizontalSwipe(deltaX, deltaY)) return false

                if (deltaX > 0f) {
                    handleAction(DemoAction.NEXT)
                } else {
                    handleAction(DemoAction.PREVIOUS)
                }
                return true
            }
        }
        return false
    }

    private fun resetSwipeTracking() {
        isSwipeTracking = false
        swipeHandledByFling = false
    }

    private fun isHorizontalSwipe(deltaX: Float, deltaY: Float): Boolean {
        val horizontalDistance = abs(deltaX)
        val verticalDistance = abs(deltaY)
        if (horizontalDistance < swipeDistanceThresholdPx) return false
        return horizontalDistance >= verticalDistance - swipeDirectionSlopPx
    }

    private fun handleAction(action: DemoAction) {
        when (val result = currentScreenController().handleAction(action)) {
            NavigationResult.Stay -> renderUi()
            NavigationResult.ExitApp -> finish()
            is NavigationResult.Open -> {
                navigateTo(result.screen)
                renderUi()
            }
        }
    }

    private fun navigateTo(screen: DemoScreen) {
        if (currentScreen == screen) return
        currentScreenController().onExit()
        currentScreen = screen
        currentScreenController().onEnter()
    }

    private fun renderUi() {
        screenControllers.values.forEach { controller ->
            controller.setVisible(controller.screen == currentScreen)
            controller.render()
        }
        breadcrumbView.text = currentScreen.breadcrumb(this)
        controlHelpView.text = getString(currentScreen.controlHelpResId)
    }

    private fun currentScreenController(): ScreenController = screenControllers.getValue(currentScreen)

    private fun startVoiceIfPossible() {
        if (!hasRecordAudioPermission()) {
            microphoneScreenController.setVoiceStatus(getString(R.string.voice_permission_waiting))
            return
        }

        if (voiceRecognizer == null) {
            voiceRecognizer = VoiceCommandRecognizer(
                context = this,
                commands = listOf("select", "back", "next", "previous"),
                onResult = { command ->
                    runOnUiThread {
                        microphoneScreenController.setRecognizedCommand(command)
                        when (command) {
                            "select" -> handleAction(DemoAction.SELECT)
                            "back" -> handleAction(DemoAction.BACK)
                            "next" -> handleAction(DemoAction.NEXT)
                            "previous" -> handleAction(DemoAction.PREVIOUS)
                        }
                    }
                },
                onPartialText = { text ->
                    runOnUiThread {
                        microphoneScreenController.setPartialText(text)
                    }
                },
                onAudioLevel = { level ->
                    runOnUiThread {
                        microphoneScreenController.setAudioLevel(level)
                    }
                },
                onStatus = { message ->
                    runOnUiThread {
                        microphoneScreenController.setVoiceStatus(message)
                    }
                },
                onErrorText = { message ->
                    runOnUiThread {
                        microphoneScreenController.setVoiceStatus(message)
                    }
                }
            )
        }

        voiceRecognizer?.start()
    }

    private fun initialVoiceStatus(): String {
        return if (hasRecordAudioPermission()) {
            getString(R.string.voice_model_loading)
        } else {
            getString(R.string.voice_permission_waiting)
        }
    }
}
