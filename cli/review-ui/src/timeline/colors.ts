import type { ReviewSample } from "../api/types.ts";

const BOOLEAN_COLORS: Record<"false" | "true", string> = {
  false: "#57606a",
  true: "#0969da",
};

function compareCodePoints(left: string, right: string): number {
  const leftCodePoints = Array.from(left, (character) => character.codePointAt(0) ?? 0);
  const rightCodePoints = Array.from(right, (character) => character.codePointAt(0) ?? 0);
  const sharedLength = Math.min(leftCodePoints.length, rightCodePoints.length);

  for (let index = 0; index < sharedLength; index += 1) {
    if (leftCodePoints[index] !== rightCodePoints[index]) {
      return leftCodePoints[index] - rightCodePoints[index];
    }
  }

  return leftCodePoints.length - rightCodePoints.length;
}

function normalizeJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeJson);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => compareCodePoints(left, right))
        .map(([key, item]) => [key, normalizeJson(item)]),
    );
  }
  return value;
}

export function expectationColorKey(sample: ReviewSample): string {
  if (!sample.has_expectation) return sample.ignore ? "ignored" : "draft";
  try {
    return `${sample.expect_type}:${JSON.stringify(normalizeJson(JSON.parse(sample.expect_json)))}`;
  } catch {
    return `${sample.expect_type}:${sample.expect_json}`;
  }
}

function hashText(text: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

export function expectationColor(sample: ReviewSample): string {
  if (!sample.has_expectation) return sample.ignore ? "#6e7781" : "#9a6700";
  if (sample.expect_type === "boolean" && sample.expect_json in BOOLEAN_COLORS) {
    return BOOLEAN_COLORS[sample.expect_json as "false" | "true"];
  }

  const hash = hashText(expectationColorKey(sample));
  const hue = hash % 360;
  const saturation = 58 + ((hash >>> 8) % 17);
  const strokeLightness = 32 + ((hash >>> 24) % 12);
  return `hsl(${hue} ${saturation}% ${strokeLightness}%)`;
}
