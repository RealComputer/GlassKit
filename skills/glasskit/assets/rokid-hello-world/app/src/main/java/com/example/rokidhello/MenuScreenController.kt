package com.example.rokidhello

import android.content.Context
import android.graphics.Typeface
import android.view.View
import android.widget.TextView

internal class MenuScreenController(
    panelView: View
) : ViewScreenController(ScreenId.MENU, panelView) {

    private data class MenuItem(
        val labelResId: Int,
        val targetScreen: ScreenId,
        val textView: TextView
    )

    private val menuItems = listOf(
        MenuItem(
            labelResId = R.string.menu_hello,
            targetScreen = ScreenId.HELLO,
            textView = panelView.findViewById(R.id.menuHelloItem)
        ),
        MenuItem(
            labelResId = R.string.menu_hola,
            targetScreen = ScreenId.HOLA,
            textView = panelView.findViewById(R.id.menuHolaItem)
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

    override fun handleAction(action: NavigationAction): ScreenCommand {
        return when (action) {
            NavigationAction.SELECT -> {
                quitConfirmationArmed = false
                ScreenCommand.Open(menuItems[focusedIndex].targetScreen)
            }

            NavigationAction.BACK -> {
                if (quitConfirmationArmed) {
                    ScreenCommand.ExitApp
                } else {
                    quitConfirmationArmed = true
                    ScreenCommand.Stay
                }
            }

            NavigationAction.NEXT -> {
                quitConfirmationArmed = false
                focusedIndex = (focusedIndex + 1).coerceAtMost(menuItems.lastIndex)
                ScreenCommand.Stay
            }

            NavigationAction.PREVIOUS -> {
                quitConfirmationArmed = false
                focusedIndex = (focusedIndex - 1).coerceAtLeast(0)
                ScreenCommand.Stay
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
