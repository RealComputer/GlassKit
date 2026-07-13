import { describe, expect, it } from "vitest";
import { sample, target } from "../test/fixtures.ts";
import { canDeleteFromTarget, createSampleAt } from "./editing.ts";

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

  it("protects the accepted last sample but permits cancelling an unsaved first sample", () => {
    const draft = target("status", [sample("only", 1)]);
    expect(canDeleteFromTarget(draft, target("status", [sample("disk", 1)]), "only")).toBe(false);
    expect(canDeleteFromTarget(draft, target("status", []), "only")).toBe(true);
    expect(canDeleteFromTarget(draft, target("status", []), "only", true)).toBe(false);
  });
});
