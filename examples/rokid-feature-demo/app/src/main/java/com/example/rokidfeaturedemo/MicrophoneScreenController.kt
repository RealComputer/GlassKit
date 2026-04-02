package com.example.rokidfeaturedemo

import android.view.View
import android.widget.TextView

internal class MicrophoneScreenController(
    panelView: View,
    private val hasRecordAudioPermission: () -> Boolean,
    private val initialVoiceStatus: () -> String
) : PanelScreenController(DemoScreen.MICROPHONE, panelView) {

    private val micStatusView: TextView = panelView.findViewById(R.id.micStatusView)
    private val micLevelView: TextView = panelView.findViewById(R.id.micLevelView)
    private val partialResultView: TextView = panelView.findViewById(R.id.partialResultView)
    private val lastCommandView: TextView = panelView.findViewById(R.id.lastCommandView)
    private val levelMeterView: LevelMeterView = panelView.findViewById(R.id.levelMeterView)

    private var voiceStatus = ""
    private var micLevelPercent = 0
    private var partialText = ""
    private var lastCommandText = panelView.context.getString(R.string.last_command_idle)

    override fun render() {
        micStatusView.text = when {
            !hasRecordAudioPermission() -> panelView.context.getString(R.string.mic_permission_needed)
            voiceStatus.isNotBlank() -> voiceStatus
            else -> initialVoiceStatus()
        }
        micLevelView.text = panelView.context.getString(R.string.mic_level_template, micLevelPercent)
        partialResultView.text = if (partialText.isBlank()) {
            panelView.context.getString(R.string.partial_idle)
        } else {
            panelView.context.getString(R.string.partial_template, partialText)
        }
        lastCommandView.text = lastCommandText
        levelMeterView.levelPercent = micLevelPercent
    }

    override fun handleAction(action: DemoAction): NavigationResult {
        return if (action == DemoAction.BACK) {
            NavigationResult.Open(DemoScreen.MENU)
        } else {
            NavigationResult.Stay
        }
    }

    override fun onPermissionsUpdated() {
        render()
    }

    fun setVoiceStatus(message: String) {
        voiceStatus = message
        render()
    }

    fun setAudioLevel(levelPercent: Int) {
        micLevelPercent = levelPercent
        render()
    }

    fun setPartialText(text: String) {
        partialText = text
        render()
    }

    fun setRecognizedCommand(command: String) {
        lastCommandText = lastCommandView.context.getString(R.string.voice_match_template, command)
        render()
    }
}
