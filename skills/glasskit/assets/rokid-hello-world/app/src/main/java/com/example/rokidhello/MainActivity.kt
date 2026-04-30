package com.example.rokidhello

import android.annotation.SuppressLint
import android.app.Activity
import android.os.Bundle
import android.view.GestureDetector
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.ViewConfiguration
import android.view.WindowManager
import kotlin.math.abs

class MainActivity : Activity() {

    companion object {
        private const val SWIPE_DISTANCE_THRESHOLD_DP = 56f
    }

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
                    handleSelect()
                    return true
                }

                override fun onDoubleTap(e: MotionEvent): Boolean {
                    handleBack()
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
                        handleNext()
                    } else {
                        handlePrevious()
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
                handleSelect()
                true
            }

            KeyEvent.KEYCODE_BACK -> {
                handleBack()
                true
            }

            KeyEvent.KEYCODE_DPAD_DOWN -> {
                handleNext()
                true
            }

            KeyEvent.KEYCODE_DPAD_UP -> {
                handlePrevious()
                true
            }

            else -> super.onKeyUp(keyCode, event)
        }
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
                    handleNext()
                } else {
                    handlePrevious()
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

    private fun handleSelect() = Unit

    private fun handleBack() {
        finish()
    }

    private fun handleNext() = Unit

    private fun handlePrevious() = Unit
}
