package com.example.rokidfeaturedemo

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import kotlin.math.max
import kotlin.math.roundToInt

class LevelMeterView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    private val activePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.FILL
    }

    private val inactivePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = context.dpToPx(2f)
    }

    private val barRect = RectF()

    var levelPercent: Int = 0
        set(value) {
            val clamped = value.coerceIn(0, 100)
            if (field == clamped) return
            field = clamped
            invalidate()
        }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val barCount = 12
        val gap = context.dpToPx(8f)
        val availableWidth = width - paddingLeft - paddingRight
        val availableHeight = height - paddingTop - paddingBottom
        if (availableWidth <= 0 || availableHeight <= 0) return

        val totalGap = gap * (barCount - 1)
        val barWidth = max(1f, (availableWidth - totalGap) / barCount)
        val activeBars = ((levelPercent / 100f) * barCount).roundToInt().coerceIn(0, barCount)

        for (index in 0 until barCount) {
            val left = paddingLeft + index * (barWidth + gap)
            val right = left + barWidth
            val barHeightRatio = (index + 3) / (barCount + 2f)
            val top = paddingTop + availableHeight * (1f - barHeightRatio)
            val bottom = (paddingTop + availableHeight).toFloat()
            barRect.set(left, top, right, bottom)
            val radius = context.dpToPx(4f)
            if (index < activeBars) {
                canvas.drawRoundRect(barRect, radius, radius, activePaint)
            } else {
                canvas.drawRoundRect(barRect, radius, radius, inactivePaint)
            }
        }
    }

    private fun Context.dpToPx(value: Float): Float = value * resources.displayMetrics.density
}
