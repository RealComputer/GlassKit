package com.example.rokidfeaturedemo

import android.content.Context
import android.view.View

internal enum class DemoScreen(
    val labelResId: Int,
    val controlHelpResId: Int
) {
    MENU(R.string.menu_label, R.string.control_help_menu),
    CAMERA(R.string.camera_label, R.string.control_help_camera),
    AUDIO(R.string.audio_label, R.string.control_help_audio),
    MICROPHONE(R.string.microphone_label, R.string.control_help_microphone);

    fun breadcrumb(context: Context): String {
        val label = context.getString(labelResId)
        return if (this == MENU) {
            label
        } else {
            "${context.getString(R.string.menu_label)} / $label"
        }
    }
}

internal enum class DemoAction {
    SELECT,
    BACK,
    NEXT,
    PREVIOUS
}

internal sealed interface NavigationResult {
    object Stay : NavigationResult
    object ExitApp : NavigationResult
    data class Open(val screen: DemoScreen) : NavigationResult
}

internal interface ScreenController {
    val screen: DemoScreen

    fun setVisible(visible: Boolean)

    fun render()

    fun handleAction(action: DemoAction): NavigationResult

    fun onEnter() {}

    fun onExit() {}

    fun onHostStart() {}

    fun onHostStop() {}

    fun onPermissionsUpdated() {}

    fun onDestroy() {}
}

internal abstract class PanelScreenController(
    final override val screen: DemoScreen,
    protected val panelView: View
) : ScreenController {

    override fun setVisible(visible: Boolean) {
        panelView.visibility = if (visible) View.VISIBLE else View.GONE
    }

    override fun render() = Unit

    override fun handleAction(action: DemoAction): NavigationResult = NavigationResult.Stay
}
