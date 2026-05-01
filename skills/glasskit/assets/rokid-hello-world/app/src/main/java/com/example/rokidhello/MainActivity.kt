package com.example.rokidhello

import android.os.Bundle
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.WindowManager
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
            onSelect = ::handleSelect,
            onBack = { onBackPressedDispatcher.onBackPressed() },
            onNext = ::handleNext,
            onPrevious = ::handlePrevious
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        onBackPressedDispatcher.addCallback(this, backCallback)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)
    }

    // Phone/emulator touchscreen input.
    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        return navigationInputController.onTouchEvent(event) || super.dispatchTouchEvent(event)
    }

    // Rokid touchpad gesture input.
    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return navigationInputController.onKeyUp(keyCode) || super.onKeyUp(keyCode, event)
    }

    // Rokid touchpad tap or phone/emulator touchscreen tap.
    private fun handleSelect() = Unit

    // Rokid touchpad double tap or phone/emulator touchscreen double tap.
    // Keep Back available on the root screen so users can exit the app.
    // Inner screens can use Back for in-app navigation, while the root screen exits.
    // Tip: on the root screen, first Back can show "Double tap again to quit" to prevent accidental close.
    private fun handleBack() {
        finish()
    }

    // Rokid touchpad swipe forward or phone/emulator touchscreen swipe right.
    private fun handleNext() = Unit

    // Rokid touchpad swipe backward or phone/emulator touchscreen swipe left.
    private fun handlePrevious() = Unit
}
