package com.example.rokidhello

import android.content.Context
import android.view.GestureDetector
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.ViewConfiguration
import kotlin.math.abs

// Maps Rokid Glasses touchpad keys and phone/emulator touchscreen gestures to app navigation actions.
class NavigationInputController(
    context: Context,
    private val onSelect: () -> Unit,
    private val onBack: () -> Unit,
    private val onNext: () -> Unit,
    private val onPrevious: () -> Unit
) {

    companion object {
        private const val SWIPE_DISTANCE_THRESHOLD_DP = 56f
    }

    private var swipeStartX = 0f
    private var swipeStartY = 0f
    private var isSwipeTracking = false
    private var swipeHandledByFling = false

    private val swipeDistanceThresholdPx = SWIPE_DISTANCE_THRESHOLD_DP * context.resources.displayMetrics.density
    private val swipeDirectionSlopPx = ViewConfiguration.get(context).scaledTouchSlop * 4f
    private val gestureDetector = GestureDetector(
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
                val deltaX = e2.x - start.x
                val deltaY = e2.y - start.y
                if (!isHorizontalSwipe(deltaX, deltaY)) return false

                swipeHandledByFling = true
                if (deltaX > 0f) {
                    onNext()
                } else {
                    onPrevious()
                }
                return true
            }
        }
    )

    fun onTouchEvent(event: MotionEvent): Boolean {
        val handledByGestureDetector = gestureDetector.onTouchEvent(event)
        val handledBySwipeFallback = handleSwipeFallback(event)
        return handledByGestureDetector || handledBySwipeFallback
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
                    onNext()
                } else {
                    onPrevious()
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
}
