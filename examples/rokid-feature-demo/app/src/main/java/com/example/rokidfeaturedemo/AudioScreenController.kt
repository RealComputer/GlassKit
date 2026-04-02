package com.example.rokidfeaturedemo

import android.media.AudioManager
import android.media.ToneGenerator
import android.view.View
import android.widget.TextView

internal class AudioScreenController(
    panelView: View
) : PanelScreenController(DemoScreen.AUDIO, panelView) {

    private data class ToneOption(
        val toneType: Int
    )

    private val audioItems = listOf<TextView>(
        panelView.findViewById(R.id.audioToneOne),
        panelView.findViewById(R.id.audioToneTwo),
        panelView.findViewById(R.id.audioToneThree)
    )
    private val toneOptions = listOf(
        ToneOption(ToneGenerator.TONE_PROP_BEEP),
        ToneOption(ToneGenerator.TONE_PROP_ACK),
        ToneOption(ToneGenerator.TONE_PROP_NACK)
    )
    private val toneGenerator = runCatching {
        ToneGenerator(AudioManager.STREAM_MUSIC, 100)
    }.getOrNull()

    private var toneIndex = 0

    override fun onEnter() {
        toneIndex = 0
        playFocusedTone()
    }

    override fun onDestroy() {
        toneGenerator?.release()
    }

    override fun render() {
        audioItems.forEachIndexed { index, item ->
            item.applyHudSelection(index == toneIndex)
        }
    }

    override fun handleAction(action: DemoAction): NavigationResult {
        return when (action) {
            DemoAction.SELECT -> {
                playFocusedTone()
                NavigationResult.Stay
            }

            DemoAction.BACK -> NavigationResult.Open(DemoScreen.MENU)
            DemoAction.NEXT -> {
                val nextIndex = (toneIndex + 1).coerceAtMost(audioItems.lastIndex)
                if (nextIndex != toneIndex) {
                    toneIndex = nextIndex
                    playFocusedTone()
                }
                NavigationResult.Stay
            }

            DemoAction.PREVIOUS -> {
                val previousIndex = (toneIndex - 1).coerceAtLeast(0)
                if (previousIndex != toneIndex) {
                    toneIndex = previousIndex
                    playFocusedTone()
                }
                NavigationResult.Stay
            }
        }
    }

    private fun playFocusedTone() {
        val option = toneOptions[toneIndex]
        toneGenerator?.startTone(option.toneType, 200)
    }
}
