package com.example.rokidrfdetr

data class SpeedrunSplit(val label: String)

data class SpeedrunGroup(val name: String, val splits: List<SpeedrunSplit>)

data class SpeedrunConfig(val groups: List<SpeedrunGroup>) {
    val totalSplits: Int
        get() = groups.sumOf { it.splits.size }
}

enum class RunState {
    IDLE,
    RUNNING,
    FINISHED
}

data class SpeedrunState(
    val runState: RunState,
    val activeIndex: Int,
    val completedCount: Int
)
