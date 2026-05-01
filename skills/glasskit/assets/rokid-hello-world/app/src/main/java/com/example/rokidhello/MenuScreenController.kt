package com.example.rokidhello

import android.content.Context
import android.graphics.Typeface
import android.view.View
import android.widget.TextView

internal class MenuScreenController(
    panelView: View
) : PanelScreenController(AppScreen.MENU, panelView) {

    private data class MenuItem(
        val labelResId: Int,
        val targetScreen: AppScreen,
        val textView: TextView
    )

    private val menuItems = listOf(
        MenuItem(
            labelResId = R.string.menu_hello,
            targetScreen = AppScreen.HELLO,
            textView = panelView.findViewById(R.id.menuHelloItem)
        )
    )

    private var focusedIndex = 0
    private var quitConfirmationArmed = false

    override fun render() {
        menuItems.forEachIndexed { index, item ->
            item.textView.applyMenuItemStyle(
                label = panelView.context.getString(item.labelResId),
                selected = index == focusedIndex
            )
        }
    }

    override fun handleAction(action: AppAction): NavigationResult {
        return when (action) {
            AppAction.SELECT -> {
                quitConfirmationArmed = false
                NavigationResult.Open(menuItems[focusedIndex].targetScreen)
            }

            AppAction.BACK -> {
                if (quitConfirmationArmed) {
                    NavigationResult.ExitApp
                } else {
                    quitConfirmationArmed = true
                    NavigationResult.Stay
                }
            }

            AppAction.NEXT -> {
                quitConfirmationArmed = false
                focusedIndex = (focusedIndex + 1).coerceAtMost(menuItems.lastIndex)
                NavigationResult.Stay
            }

            AppAction.PREVIOUS -> {
                quitConfirmationArmed = false
                focusedIndex = (focusedIndex - 1).coerceAtLeast(0)
                NavigationResult.Stay
            }
        }
    }

    override fun navigationHint(context: Context): String {
        return if (quitConfirmationArmed) {
            context.getString(R.string.nav_menu_quit_confirm)
        } else {
            context.getString(R.string.nav_menu_default)
        }
    }

    private fun TextView.applyMenuItemStyle(label: String, selected: Boolean) {
        text = if (selected) "> $label" else "  $label"
        typeface = Typeface.create(
            Typeface.MONOSPACE,
            if (selected) Typeface.BOLD else Typeface.NORMAL
        )
        setTextColor(
            context.getColor(
                if (selected) R.color.hud_foreground else R.color.hud_foreground_muted
            )
        )
    }
}
