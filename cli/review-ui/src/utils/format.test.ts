import { describe, expect, it } from "vitest";
import { formatTime } from "./format.ts";

describe("formatTime", () => {
  it("carries rounded milliseconds into the next minute", () => {
    expect(formatTime(59.9996)).toBe("01:00.000");
    expect(formatTime(119.9996, true)).toBe("02:00.000s");
  });
});
