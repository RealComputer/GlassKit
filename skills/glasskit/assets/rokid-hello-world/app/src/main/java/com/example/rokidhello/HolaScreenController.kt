package com.example.rokidhello

import android.content.Context
import android.view.View

internal class HolaScreenController(
    panelView: View
) : ViewScreenController(ScreenId.HOLA, panelView) {

    override fun handleAction(action: NavigationAction): ScreenCommand {
        return if (action == NavigationAction.BACK) {
            ScreenCommand.Open(ScreenId.MENU)
        } else {
            ScreenCommand.Stay
        }
    }

    override fun navigationHint(context: Context): String {
        return context.getString(R.string.nav_content)
    }
}
