package com.example.rokidfeaturedemo

import android.view.View
import android.widget.TextView

internal class MenuScreenController(
    panelView: View
) : PanelScreenController(DemoScreen.MENU, panelView) {

    private val menuItems = listOf<TextView>(
        panelView.findViewById(R.id.menuCameraItem),
        panelView.findViewById(R.id.menuAudioItem),
        panelView.findViewById(R.id.menuMicItem)
    )

    private var menuIndex = 0

    override fun render() {
        menuItems.forEachIndexed { index, item ->
            item.applyHudSelection(index == menuIndex)
        }
    }

    override fun handleAction(action: DemoAction): NavigationResult {
        return when (action) {
            DemoAction.SELECT -> NavigationResult.Open(
                when (menuIndex) {
                    0 -> DemoScreen.CAMERA
                    1 -> DemoScreen.AUDIO
                    else -> DemoScreen.MICROPHONE
                }
            )

            DemoAction.BACK -> NavigationResult.ExitApp
            DemoAction.NEXT -> {
                menuIndex = (menuIndex + 1).coerceAtMost(menuItems.lastIndex)
                NavigationResult.Stay
            }

            DemoAction.PREVIOUS -> {
                menuIndex = (menuIndex - 1).coerceAtLeast(0)
                NavigationResult.Stay
            }
        }
    }
}
