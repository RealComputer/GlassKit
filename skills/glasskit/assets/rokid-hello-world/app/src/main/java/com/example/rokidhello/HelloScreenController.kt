package com.example.rokidhello

import android.content.Context
import android.view.View

internal class HelloScreenController(
    panelView: View
) : PanelScreenController(AppScreen.HELLO, panelView) {

    override fun handleAction(action: AppAction): NavigationResult {
        return if (action == AppAction.BACK) {
            NavigationResult.Open(AppScreen.MENU)
        } else {
            NavigationResult.Stay
        }
    }

    override fun navigationHint(context: Context): String {
        return context.getString(R.string.nav_hello)
    }
}
