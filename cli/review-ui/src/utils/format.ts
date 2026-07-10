import type { ReviewPoint } from "../api/types.ts";

export function formatTime(seconds: number, includeUnit = false): string {
  if (!Number.isFinite(seconds)) return "--:--.---";
  const totalMilliseconds = Math.round(Math.max(0, seconds) * 1000);
  const minutes = Math.floor(totalMilliseconds / 60_000);
  const remainder = (totalMilliseconds % 60_000) / 1000;
  const formatted = `${String(minutes).padStart(2, "0")}:${remainder.toFixed(3).padStart(6, "0")}`;
  return includeUnit ? `${formatted}s` : formatted;
}

export function formatSeconds(seconds: number): string {
  return `${seconds.toFixed(3)}s`;
}

export function expectationSummary(point: ReviewPoint, maxLength = 46): string {
  let text = point.expect_json;
  if (point.expect_type === "string") {
    try {
      text = JSON.parse(point.expect_json) as string;
    } catch {
      // The backend has already validated loaded values. Retain the raw text if
      // an in-progress draft somehow reaches this helper.
    }
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

export function effectiveCompare(point: ReviewPoint): string {
  if (point.compare.mode) return point.compare.mode;
  return point.expect_type === "number" ? "numeric (auto)" : "exact (auto)";
}
