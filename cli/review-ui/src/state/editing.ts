import type { ReviewPoint, ReviewTarget } from '../api/types.ts'

function closestPoint(target: ReviewTarget, timestamp: number) {
  return target.points.reduce<ReviewPoint | null>((best, point) => {
    if (!best) return point
    const distance = Math.abs(point.timestamp_s - timestamp)
    const bestDistance = Math.abs(best.timestamp_s - timestamp)
    if (distance < bestDistance) return point
    if (distance === bestDistance && point.timestamp_s < best.timestamp_s) {
      return point
    }
    return best
  }, null)
}

export function createPointAt(
  target: ReviewTarget,
  playheadTime: number,
  id: string,
): { point: ReviewPoint; duplicate: boolean } {
  const timestamp = Math.round(playheadTime * 1000) / 1000
  const duplicate = target.points.find(
    (point) => Math.abs(point.timestamp_s - timestamp) <= 1e-9,
  )
  if (duplicate) return { point: duplicate, duplicate: true }
  const source = closestPoint(target, timestamp)
  return {
    duplicate: false,
    point: {
      id,
      timestamp_s: timestamp,
      expect_type: source?.expect_type ?? 'boolean',
      expect_json: source?.expect_json ?? 'false',
      field: source?.field ?? null,
      compare: source ? { ...source.compare } : { mode: null, tolerance: null },
      comment: null,
      origin: null,
    },
  }
}

export function canDeleteFromTarget(
  draftTarget: ReviewTarget,
  acceptedTarget: ReviewTarget | undefined,
  pointId: string,
  saveInFlight = false,
): boolean {
  if (!draftTarget.points.some((point) => point.id === pointId)) return false
  if (draftTarget.points.length > 1) return true
  if (saveInFlight) return false
  return (acceptedTarget?.points.length ?? 0) === 0
}
