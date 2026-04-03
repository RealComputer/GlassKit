package com.example.rokidfeaturedemo

import android.content.Context
import android.util.AttributeSet
import android.view.View.MeasureSpec
import android.widget.FrameLayout
import kotlin.math.roundToInt

class RokidHudViewportLayout @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : FrameLayout(context, attrs) {

    companion object {
        // Rokid and the emulator both render the HUD in a 480x640 portrait viewport.
        private const val HUD_ASPECT_RATIO = 480f / 640f
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val availableWidth = MeasureSpec.getSize(widthMeasureSpec)
        val availableHeight = MeasureSpec.getSize(heightMeasureSpec)
        if (availableWidth == 0 || availableHeight == 0) {
            super.onMeasure(widthMeasureSpec, heightMeasureSpec)
            return
        }

        val availableAspectRatio = availableWidth.toFloat() / availableHeight.toFloat()
        val measuredWidth: Int
        val measuredHeight: Int

        if (availableAspectRatio > HUD_ASPECT_RATIO) {
            measuredHeight = availableHeight
            measuredWidth = (measuredHeight * HUD_ASPECT_RATIO).roundToInt()
        } else {
            measuredWidth = availableWidth
            measuredHeight = (measuredWidth / HUD_ASPECT_RATIO).roundToInt()
        }

        super.onMeasure(
            MeasureSpec.makeMeasureSpec(measuredWidth, MeasureSpec.EXACTLY),
            MeasureSpec.makeMeasureSpec(measuredHeight, MeasureSpec.EXACTLY)
        )
        setMeasuredDimension(measuredWidth, measuredHeight)
    }
}
