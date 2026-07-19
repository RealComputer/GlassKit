import { describe, expect, it } from "vitest";
import { sample, target } from "../test/fixtures.ts";
import { canDeleteFromTarget, createSampleAt, mostRecentSampleAt } from "./editing.ts";

describe("sample editing helpers", () => {
  it("rounds a new time and copies the closest payload without notes or origin", () => {
    const earlier = {
      ...sample("earlier", 1, "true"),
      field: "result.ok",
      comment: "do not copy",
      ignore: "do not copy",
    };
    const later = sample("later", 3, "false");
    const created = createSampleAt(target("status", [earlier, later]), 1.23456, "new-id");
    expect(created.duplicate).toBe(false);
    expect(created.sample).toMatchObject({
      id: "new-id",
      timestamp_s: 1.235,
      expect_json: "true",
      field: "result.ok",
      comment: null,
      ignore: null,
      origin: null,
    });
  });

  it("selects an existing sample at the rounded duplicate time", () => {
    const existing = sample("existing", 1.235);
    const created = createSampleAt(target("status", [existing]), 1.2346, "unused");
    expect(created).toEqual({ sample: existing, duplicate: true });
  });

  it("uses a real default expectation when the nearest sample is still a draft", () => {
    const draft = { ...sample("draft", 1, "null"), has_expectation: false };

    const created = createSampleAt(target("status", [draft]), 2, "created");

    expect(created.sample.has_expectation).toBe(true);
    expect(created.sample.expect_type).toBe("boolean");
    expect(created.sample.expect_json).toBe("false");
  });

  it("finds the most recently crossed sample in an unsorted target", () => {
    const samples = [sample("later", 3), sample("first", 1), sample("recent", 2)];
    const status = target("status", samples);

    expect(mostRecentSampleAt(status, 0.999)).toBeUndefined();
    expect(mostRecentSampleAt(status, 2)).toBe(samples[2]);
    expect(mostRecentSampleAt(status, 2.5)).toBe(samples[2]);
    expect(mostRecentSampleAt(status, 4)).toBe(samples[0]);
  });

  it("protects the accepted last sample but permits cancelling an unsaved first sample", () => {
    const draft = target("status", [sample("only", 1)]);
    expect(canDeleteFromTarget(draft, target("status", [sample("disk", 1)]), "only")).toBe(false);
    expect(canDeleteFromTarget(draft, target("status", []), "only")).toBe(true);
    expect(canDeleteFromTarget(draft, target("status", []), "only", true)).toBe(false);
  });
});
