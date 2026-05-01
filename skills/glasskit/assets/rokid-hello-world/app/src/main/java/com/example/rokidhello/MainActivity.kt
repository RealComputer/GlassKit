package com.example.rokidhello

import android.os.Bundle
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.WindowManager
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback

class MainActivity : ComponentActivity() {

    private val backCallback = object : OnBackPressedCallback(true) {
        override fun handleOnBackPressed() {
            handleBack()
        }
    }

    private val navigationInputController by lazy {
        NavigationInputController(
            context = this,
            onSelect = { handleAction(AppAction.SELECT) },
            onBack = { onBackPressedDispatcher.onBackPressed() },
            onNext = { handleAction(AppAction.NEXT) },
            onPrevious = { handleAction(AppAction.PREVIOUS) }
        )
    }

    private lateinit var screenTitleView: TextView
    private lateinit var navigationHintView: TextView
    private lateinit var screenControllers: Map<AppScreen, ScreenController>

    private var currentScreen = AppScreen.MENU

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        onBackPressedDispatcher.addCallback(this, backCallback)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)
        bindViews()
        bindScreenControllers()
        currentScreenController().onEnter()
        renderUi()
    }

    override fun onDestroy() {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onDestroy()
    }

    // Phone/emulator touchscreen input.
    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        return navigationInputController.onTouchEvent(event) || super.dispatchTouchEvent(event)
    }

    // Rokid touchpad gesture input.
    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return navigationInputController.onKeyUp(keyCode) || super.onKeyUp(keyCode, event)
    }

    private fun handleBack() {
        handleAction(AppAction.BACK)
    }

    private fun bindViews() {
        screenTitleView = findViewById(R.id.screenTitleView)
        navigationHintView = findViewById(R.id.navigationHintView)
    }

    private fun bindScreenControllers() {
        val menuController = MenuScreenController(findViewById(R.id.menuPanel))
        val helloController = HelloScreenController(findViewById(R.id.helloPanel))
        screenControllers = linkedMapOf(
            menuController.screen to menuController,
            helloController.screen to helloController
        )
    }

    private fun handleAction(action: AppAction) {
        when (val result = currentScreenController().handleAction(action)) {
            NavigationResult.Stay -> renderUi()
            NavigationResult.ExitApp -> finish()
            is NavigationResult.Open -> {
                navigateTo(result.screen)
                renderUi()
            }
        }
    }

    private fun navigateTo(screen: AppScreen) {
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
        screenTitleView.setText(currentScreen.titleResId)
        navigationHintView.text = currentScreenController().navigationHint(this)
    }

    private fun currentScreenController(): ScreenController = screenControllers.getValue(currentScreen)
}
