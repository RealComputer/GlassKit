package com.example.rokidhello

import android.content.Context
import android.view.View

internal enum class AppScreen(
    val titleResId: Int
) {
    MENU(R.string.screen_menu_title),
    HELLO(R.string.screen_hello_title)
}

internal enum class AppAction {
    SELECT,
    BACK,
    NEXT,
    PREVIOUS
}

internal sealed interface NavigationResult {
    object Stay : NavigationResult
    object ExitApp : NavigationResult
    data class Open(val screen: AppScreen) : NavigationResult
}

internal interface ScreenController {
    val screen: AppScreen

    fun setVisible(visible: Boolean)

    fun render()

    fun handleAction(action: AppAction): NavigationResult

    fun navigationHint(context: Context): String

    fun onEnter() {}

    fun onExit() {}
}

internal abstract class PanelScreenController(
    final override val screen: AppScreen,
    protected val panelView: View
) : ScreenController {

    override fun setVisible(visible: Boolean) {
        panelView.visibility = if (visible) View.VISIBLE else View.GONE
    }

    override fun render() = Unit
}
