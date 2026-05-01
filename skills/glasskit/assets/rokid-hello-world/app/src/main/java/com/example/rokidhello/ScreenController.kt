package com.example.rokidhello

import android.content.Context
import android.view.View

internal enum class ScreenId(
    val titleResId: Int
) {
    MENU(R.string.screen_menu_title),
    HELLO(R.string.screen_hello_title)
}

internal enum class NavigationAction {
    SELECT,
    BACK,
    NEXT,
    PREVIOUS
}

internal sealed interface ScreenCommand {
    object Stay : ScreenCommand
    object ExitApp : ScreenCommand
    data class Open(val screen: ScreenId) : ScreenCommand
}

internal interface ScreenController {
    val screen: ScreenId

    fun setVisible(visible: Boolean)

    fun render()

    fun handleAction(action: NavigationAction): ScreenCommand

    fun navigationHint(context: Context): String

    fun onEnter() {}

    fun onExit() {}
}

internal abstract class ViewScreenController(
    final override val screen: ScreenId,
    protected val panelView: View
) : ScreenController {

    override fun setVisible(visible: Boolean) {
        panelView.visibility = if (visible) View.VISIBLE else View.GONE
    }

    override fun render() = Unit
}
