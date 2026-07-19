import type { ReviewSample, ReviewTarget } from "../api/types.ts";

function closestSample(target: ReviewTarget, timestamp: number) {
  return target.samples.reduce<ReviewSample | null>((best, sample) => {
    if (!best) return sample;
    const distance = Math.abs(sample.timestamp_s - timestamp);
    const bestDistance = Math.abs(best.timestamp_s - timestamp);
    if (distance < bestDistance) return sample;
    if (distance === bestDistance && sample.timestamp_s < best.timestamp_s) {
      return sample;
    }
    return best;
  }, null);
}

export function findSampleAt(target: ReviewTarget, playheadTime: number): ReviewSample | undefined {
  const timestamp = Math.round(playheadTime * 1000) / 1000;
  return target.samples.find((sample) => Math.abs(sample.timestamp_s - timestamp) <= 1e-9);
}

export function mostRecentSampleAt(
  target: ReviewTarget,
  playheadTime: number,
): ReviewSample | undefined {
  return target.samples.reduce<ReviewSample | undefined>((mostRecent, sample) => {
    if (sample.timestamp_s > playheadTime + 1e-9) return mostRecent;
    if (!mostRecent || sample.timestamp_s > mostRecent.timestamp_s) return sample;
    return mostRecent;
  }, undefined);
}

export function createSampleAt(
  target: ReviewTarget,
  playheadTime: number,
  id: string,
): { sample: ReviewSample; duplicate: boolean } {
  const timestamp = Math.round(playheadTime * 1000) / 1000;
  const duplicate = findSampleAt(target, playheadTime);
  if (duplicate) return { sample: duplicate, duplicate: true };
  const source = closestSample(target, timestamp);
  const sourceExpectation = source?.has_expectation ? source : null;
  return {
    duplicate: false,
    sample: {
      id,
      timestamp_s: timestamp,
      has_expectation: true,
      expect_type: sourceExpectation?.expect_type ?? "boolean",
      expect_json: sourceExpectation?.expect_json ?? "false",
      field: source?.field ?? null,
      compare: sourceExpectation
        ? { ...sourceExpectation.compare }
        : { mode: null, tolerance: null },
      comment: null,
      ignore: null,
      origin: null,
    },
  };
}

export function canDeleteFromTarget(
  draftTarget: ReviewTarget,
  acceptedTarget: ReviewTarget | undefined,
  sampleId: string,
  saveInFlight = false,
): boolean {
  if (!draftTarget.samples.some((sample) => sample.id === sampleId)) return false;
  if (draftTarget.samples.length > 1) return true;
  if (saveInFlight) return false;
  return (acceptedTarget?.samples.length ?? 0) === 0;
}
