package com.example.rokidfeaturedemo

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.widget.TextView

internal fun TextView.applyHudSelection(selected: Boolean) {
    val background = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        cornerRadius = context.dpToPx(10f)
        setStroke(context.dpToPx(2f).toInt(), Color.WHITE)
        setColor(if (selected) Color.WHITE else Color.BLACK)
    }
    this.background = background
    setTextColor(if (selected) Color.BLACK else Color.WHITE)
}

private fun Context.dpToPx(value: Float): Float = value * resources.displayMetrics.density
