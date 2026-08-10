import { describe, expect, it } from "vitest";
import type { ReviewSample } from "../api/types.ts";
import {
  expectationDescription,
  expectationSummary,
  expectationTypeLabel,
  formatSeconds,
  formatTime,
} from "./format.ts";

function omittedExpectation(ignore: string | null): ReviewSample {
  return {
    id: "sample",
    timestamp_s: 1,
    has_expectation: false,
    expect_type: "null",
    expect_json: "null",
    field: null,
    compare: { mode: null, tolerance: null },
    comment: null,
    ignore,
    origin: null,
  };
}

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

describe("expectation labels", () => {
  it("distinguishes ignored omissions from incomplete drafts", () => {
    const ignored = omittedExpectation("Expected behavior is not known.");
    const draft = omittedExpectation(null);

    expect(expectationTypeLabel(ignored)).toBe("ignored");
    expect(expectationSummary(ignored)).toBe("Not required");
    expect(expectationDescription(ignored)).toBe("no expectation required");
    expect(expectationTypeLabel(draft)).toBe("draft");
    expect(expectationSummary(draft)).toBe("Draft");
    expect(expectationDescription(draft)).toBe("expected Draft");
  });
});
