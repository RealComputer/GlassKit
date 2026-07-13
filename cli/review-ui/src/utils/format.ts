import type { ReviewSample } from "../api/types.ts";

export function formatTime(seconds: number, includeUnit = false): string {
  if (!Number.isFinite(seconds)) return "--:--.---";
  const totalMilliseconds = Math.round(Math.max(0, seconds) * 1000);
  const minutes = Math.floor(totalMilliseconds / 60_000);
  const remainder = (totalMilliseconds % 60_000) / 1000;
  const formatted = `${String(minutes).padStart(2, "0")}:${remainder.toFixed(3).padStart(6, "0")}`;
  return includeUnit ? `${formatted}s` : formatted;
}

export function formatSeconds(seconds: number): string {
  const rounded = Number(seconds.toFixed(3));
  return `${Object.is(rounded, -0) ? 0 : rounded}s`;
}

export function expectationSummary(sample: ReviewSample, maxLength = 46): string {
  let text = sample.expect_json;
  if (sample.expect_type === "string") {
    try {
      text = JSON.parse(sample.expect_json) as string;
    } catch {
      // The backend has already validated loaded values. Retain the raw text if
      // an in-progress draft somehow reaches this helper.
    }
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

export function effectiveCompare(sample: ReviewSample): string {
  if (sample.compare.mode) return sample.compare.mode;
  return sample.expect_type === "number" ? "numeric (auto)" : "exact (auto)";
}
