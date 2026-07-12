import { describe, expect, it } from "vitest";
import type { ReviewSample } from "../api/types.ts";
import { expectationColor, expectationColorKey } from "./colors.ts";

function sample(expect_type: ReviewSample["expect_type"], expect_json: string): ReviewSample {
  return {
    id: "sample",
    timestamp_s: 1,
    expect_type,
    expect_json,
    field: null,
    compare: { mode: null, tolerance: null },
    comment: null,
    origin: null,
  };
}

describe("timeline expectation colors", () => {
  it("uses the same color for the same typed value", () => {
    expect(expectationColor(sample("string", '"ready"'))).toEqual(
      expectationColor(sample("string", '"ready"')),
    );
    expect(expectationColor(sample("boolean", "false"))).toBe("#57606a");
    expect(expectationColor(sample("boolean", "true"))).toBe("#0969da");
  });

  it("distinguishes types and canonicalizes object key order", () => {
    expect(expectationColorKey(sample("number", "1"))).not.toBe(
      expectationColorKey(sample("string", '"1"')),
    );
    expect(expectationColorKey(sample("object", '{"first":1,"second":2}'))).toBe(
      expectationColorKey(sample("object", '{"second":2,"first":1}')),
    );
  });

  it("canonicalizes distinct Unicode keys independently of locale collation", () => {
    expect(expectationColorKey(sample("object", '{"é":1,"é":2}'))).toBe(
      expectationColorKey(sample("object", '{"é":2,"é":1}')),
    );
  });
});
