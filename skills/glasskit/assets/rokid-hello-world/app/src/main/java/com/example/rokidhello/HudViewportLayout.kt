package com.example.rokidhello

import android.content.Context
import android.util.AttributeSet
import android.util.DisplayMetrics
import android.view.View
import android.view.View.MeasureSpec
import android.widget.FrameLayout
import kotlin.math.min
import kotlin.math.roundToInt

class HudViewportLayout @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : FrameLayout(context, attrs) {

    companion object {
        // Verified on Rokid Glasses: 480x640 physical pixels at 240 dpi.
        private const val HUD_REFERENCE_WIDTH_PX = 480f
        private const val HUD_REFERENCE_HEIGHT_PX = 640f
        private const val HUD_REFERENCE_DENSITY_DPI = 240f
        private const val HUD_ASPECT_RATIO = HUD_REFERENCE_WIDTH_PX / HUD_REFERENCE_HEIGHT_PX
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

        val designWidthPx = designWidthPx()
        val designHeightPx = designHeightPx()
        val childWidthSpec = MeasureSpec.makeMeasureSpec(designWidthPx, MeasureSpec.EXACTLY)
        val childHeightSpec = MeasureSpec.makeMeasureSpec(designHeightPx, MeasureSpec.EXACTLY)

        for (index in 0 until childCount) {
            val child = getChildAt(index)
            if (child.visibility == View.GONE) continue
            child.measure(childWidthSpec, childHeightSpec)
        }

        setMeasuredDimension(measuredWidth, measuredHeight)
    }

    override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
        val designWidthPx = designWidthPx()
        val designHeightPx = designHeightPx()
        val scale = min(width.toFloat() / designWidthPx, height.toFloat() / designHeightPx)
        val translationX = (width - designWidthPx * scale) / 2f
        val translationY = (height - designHeightPx * scale) / 2f

        for (index in 0 until childCount) {
            val child = getChildAt(index)
            if (child.visibility == View.GONE) continue

            child.layout(0, 0, designWidthPx, designHeightPx)
            child.pivotX = 0f
            child.pivotY = 0f
            child.scaleX = scale
            child.scaleY = scale
            child.translationX = translationX
            child.translationY = translationY
        }
    }

    private fun designWidthPx(): Int {
        return referencePixelsToCurrentPixels(HUD_REFERENCE_WIDTH_PX).roundToInt()
    }

    private fun designHeightPx(): Int {
        return referencePixelsToCurrentPixels(HUD_REFERENCE_HEIGHT_PX).roundToInt()
    }

    private fun referencePixelsToCurrentPixels(referencePixels: Float): Float {
        val referenceDp = referencePixels * DisplayMetrics.DENSITY_DEFAULT / HUD_REFERENCE_DENSITY_DPI
        return referenceDp * resources.displayMetrics.density
    }
}
