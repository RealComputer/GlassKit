import type { ReviewSample } from "../api/types.ts";

export interface ConsecutiveSampleGroup {
  id: string;
  samples: ReviewSample[];
}

function sampleSettingsKey(sample: ReviewSample): string {
  // Keep the backend JSON opaque: parsing it in JavaScript would round integers
  // beyond Number.MAX_SAFE_INTEGER and could merge distinct expectations.
  return JSON.stringify([
    sample.has_expectation,
    sample.expect_type,
    sample.expect_json,
    sample.field,
    sample.compare.mode,
    sample.compare.tolerance,
    sample.comment,
    sample.ignore,
  ]);
}

export function groupConsecutiveSamples(samples: ReviewSample[]): ConsecutiveSampleGroup[] {
  const sorted = [...samples].sort((left, right) => left.timestamp_s - right.timestamp_s);
  const groups: ConsecutiveSampleGroup[] = [];

  for (const sample of sorted) {
    const previous = groups.at(-1);
    if (previous && sampleSettingsKey(previous.samples[0]) === sampleSettingsKey(sample)) {
      previous.samples.push(sample);
    } else {
      groups.push({ id: sample.id, samples: [sample] });
    }
  }

  return groups;
}

export function regularSampleInterval(samples: ReviewSample[]): number | null {
  if (samples.length < 3) return null;
  const interval = samples[1].timestamp_s - samples[0].timestamp_s;
  if (interval <= 0) return null;

  for (let index = 2; index < samples.length; index += 1) {
    const current = samples[index].timestamp_s - samples[index - 1].timestamp_s;
    const scale = Math.max(1, Math.abs(interval), Math.abs(current));
    if (Math.abs(current - interval) > 1e-9 * scale) return null;
  }

  return interval;
}
