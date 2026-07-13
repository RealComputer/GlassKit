import { describe, expect, it } from "vitest";
import { formatSeconds, formatTime } from "./format.ts";

describe("formatTime", () => {
  it("keeps fixed millisecond precision for the transport display", () => {
    expect(formatTime(153.5)).toBe("02:33.500");
    expect(formatTime(299.767)).toBe("04:59.767");
  });

  it("carries rounded milliseconds into the next minute", () => {
    expect(formatTime(59.9996)).toBe("01:00.000");
    expect(formatTime(119.9996, true)).toBe("02:00.000s");
  });
});

describe("formatSeconds", () => {
  it("keeps useful millisecond precision without trailing zeros", () => {
    expect(formatSeconds(153.5)).toBe("153.5s");
    expect(formatSeconds(153.25)).toBe("153.25s");
    expect(formatSeconds(153.507)).toBe("153.507s");
    expect(formatSeconds(0)).toBe("0s");
  });

  it("rounds display values to milliseconds", () => {
    expect(formatSeconds(153.5076)).toBe("153.508s");
    expect(formatSeconds(-0.0001)).toBe("0s");
  });
});
