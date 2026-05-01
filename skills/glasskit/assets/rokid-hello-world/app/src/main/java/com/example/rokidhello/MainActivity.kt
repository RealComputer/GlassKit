package com.example.rokidhello

import android.annotation.SuppressLint
import android.app.Activity
import android.os.Bundle
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.WindowManager

class MainActivity : Activity() {

    private val navigationInputController by lazy {
        NavigationInputController(
            context = this,
            onSelect = ::handleSelect,
            onBack = ::handleBack,
            onNext = ::handleNext,
            onPrevious = ::handlePrevious
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        return navigationInputController.onTouchEvent(event) || super.dispatchTouchEvent(event)
    }

    @SuppressLint("GestureBackNavigation")
    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        return navigationInputController.onKeyUp(keyCode) || super.onKeyUp(keyCode, event)
    }

    private fun handleSelect() = Unit

    private fun handleBack() {
        finish()
    }

    private fun handleNext() = Unit

    private fun handlePrevious() = Unit
}
