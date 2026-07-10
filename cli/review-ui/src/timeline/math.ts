export const TIMELINE_LABEL_WIDTH = 148

export function timelineTrackWidth(
  viewportWidth: number,
  zoom: 1 | 2 | 4 | 8,
): number {
  return Math.max(1, viewportWidth - TIMELINE_LABEL_WIDTH) * zoom
}

export function timeToPosition(time: number, duration: number): number {
  if (!Number.isFinite(duration) || duration <= 0) return 0
  return Math.min(1, Math.max(0, time / duration))
}

export function positionToTime(position: number, duration: number): number {
  return Math.min(1, Math.max(0, position)) * Math.max(0, duration)
}

export function anchoredScrollLeft(
  oldScrollLeft: number,
  viewportWidth: number,
  oldTrackWidth: number,
  newTrackWidth: number,
  anchorRatio: number,
): number {
  const viewportAnchor = anchorRatio * oldTrackWidth - oldScrollLeft
  const next = anchorRatio * newTrackWidth - viewportAnchor
  return Math.max(0, Math.min(next, Math.max(0, newTrackWidth - viewportWidth)))
}

export function rulerTicks(duration: number, zoom: number): number[] {
  if (!Number.isFinite(duration) || duration <= 0) return [0]
  const targetTicks = Math.max(4, Math.min(24, Math.round(6 * zoom)))
  const roughStep = duration / targetTicks
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const normalized = roughStep / magnitude
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  const step = factor * magnitude
  const ticks: number[] = []
  for (let value = 0; value <= duration + step / 10; value += step) {
    ticks.push(Math.min(duration, value))
  }
  if (ticks[ticks.length - 1] !== duration) ticks.push(duration)
  return ticks
}

export function markerSelector(targetId: string, pointId: string): string {
  return `[data-target-id="${CSS.escape(targetId)}"][data-point-id="${CSS.escape(pointId)}"]`
}
