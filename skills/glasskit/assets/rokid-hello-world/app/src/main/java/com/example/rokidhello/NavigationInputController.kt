package com.example.rokidhello

import android.content.Context
import android.view.GestureDetector
import android.view.KeyEvent
import android.view.MotionEvent
import kotlin.math.abs

// Maps Rokid touchpad key events and phone/emulator touchscreen gestures to app navigation actions.
class NavigationInputController(
    context: Context,
    private val onSelect: () -> Unit,
    private val onBack: () -> Unit,
    private val onNext: () -> Unit,
    private val onPrevious: () -> Unit
) {

    companion object {
        private const val TOUCHSCREEN_FLING_DISTANCE_THRESHOLD_DP = 56f
    }

    private val touchscreenFlingDistanceThresholdPx =
        TOUCHSCREEN_FLING_DISTANCE_THRESHOLD_DP * context.resources.displayMetrics.density
    private val touchscreenGestureDetector = GestureDetector(
        context,
        object : GestureDetector.SimpleOnGestureListener() {
            override fun onDown(e: MotionEvent): Boolean = true

            override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
                onSelect()
                return true
            }

            override fun onDoubleTap(e: MotionEvent): Boolean {
                onBack()
                return true
            }

            override fun onFling(
                e1: MotionEvent?,
                e2: MotionEvent,
                velocityX: Float,
                velocityY: Float
            ): Boolean {
                val start = e1 ?: return false
                val horizontalMovement = e2.x - start.x
                val verticalMovement = e2.y - start.y
                if (!isHorizontalTouchscreenFling(horizontalMovement, verticalMovement)) {
                    return false
                }

                if (horizontalMovement > 0f) {
                    onNext()
                } else {
                    onPrevious()
                }
                return true
            }
        }
    )

    fun onTouchEvent(event: MotionEvent): Boolean {
        return touchscreenGestureDetector.onTouchEvent(event)
    }

    fun onKeyUp(keyCode: Int): Boolean {
        return when (keyCode) {
            // Rokid touchpad tap.
            KeyEvent.KEYCODE_ENTER -> {
                onSelect()
                true
            }

            // Rokid touchpad swipe forward.
            KeyEvent.KEYCODE_DPAD_DOWN -> {
                onNext()
                true
            }

            // Rokid touchpad swipe backward.
            KeyEvent.KEYCODE_DPAD_UP -> {
                onPrevious()
                true
            }

            else -> false
        }
    }

    private fun isHorizontalTouchscreenFling(
        horizontalMovement: Float,
        verticalMovement: Float
    ): Boolean {
        val horizontalDistance = abs(horizontalMovement)
        val verticalDistance = abs(verticalMovement)
        return horizontalDistance >= touchscreenFlingDistanceThresholdPx &&
            horizontalDistance > verticalDistance
    }
}
