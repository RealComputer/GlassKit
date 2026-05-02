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

    private val navigationInputMapper by lazy {
        NavigationInputMapper(
            context = this,
            onSelect = { handleAction(NavigationAction.SELECT) },
            onBack = { onBackPressedDispatcher.onBackPressed() },
            onNext = { handleAction(NavigationAction.NEXT) },
            onPrevious = { handleAction(NavigationAction.PREVIOUS) }
        )
    }

    private lateinit var headerTitleView: TextView
    private lateinit var footerNavigationView: TextView
    private lateinit var screenControllers: Map<ScreenId, ScreenController>

    private var currentScreen = ScreenId.MENU

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
        return navigationInputMapper.onTouchEvent(event) || super.dispatchTouchEvent(event)
    }

    // Rokid touchpad gesture input.
    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return navigationInputMapper.onKeyUp(keyCode) || super.onKeyUp(keyCode, event)
    }

    private fun handleBack() {
        handleAction(NavigationAction.BACK)
    }

    private fun bindViews() {
        headerTitleView = findViewById(R.id.headerTitleView)
        footerNavigationView = findViewById(R.id.footerNavigationView)
    }

    private fun bindScreenControllers() {
        val menuController = MenuScreenController(findViewById(R.id.menuPanel))
        val helloController = HelloScreenController(findViewById(R.id.helloPanel))
        val holaController = HolaScreenController(findViewById(R.id.holaPanel))
        screenControllers = linkedMapOf(
            menuController.screen to menuController,
            helloController.screen to helloController,
            holaController.screen to holaController
        )
    }

    private fun handleAction(action: NavigationAction) {
        when (val result = currentScreenController().handleAction(action)) {
            ScreenCommand.Stay -> renderUi()
            ScreenCommand.ExitApp -> finish()
            is ScreenCommand.Open -> {
                navigateTo(result.screen)
                renderUi()
            }
        }
    }

    private fun navigateTo(screen: ScreenId) {
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
        headerTitleView.setText(currentScreen.titleResId)
        footerNavigationView.text = currentScreenController().navigationHint(this)
    }

    private fun currentScreenController(): ScreenController = screenControllers.getValue(currentScreen)
}
