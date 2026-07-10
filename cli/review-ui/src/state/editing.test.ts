import { describe, expect, it } from "vitest";
import { point, target } from "../test/fixtures.ts";
import { canDeleteFromTarget, createPointAt } from "./editing.ts";

describe("point editing helpers", () => {
  it("rounds a new time and copies the closest payload without comment or origin", () => {
    const earlier = {
      ...point("earlier", 1, "true"),
      field: "result.ok",
      comment: "do not copy",
    };
    const later = point("later", 3, "false");
    const created = createPointAt(target("status", [earlier, later]), 1.23456, "new-id");
    expect(created.duplicate).toBe(false);
    expect(created.point).toMatchObject({
      id: "new-id",
      timestamp_s: 1.235,
      expect_json: "true",
      field: "result.ok",
      comment: null,
      origin: null,
    });
  });

  it("selects an existing point at the rounded duplicate time", () => {
    const existing = point("existing", 1.235);
    const created = createPointAt(target("status", [existing]), 1.2346, "unused");
    expect(created).toEqual({ point: existing, duplicate: true });
  });

  it("protects the accepted last point but permits cancelling an unsaved first point", () => {
    const draft = target("status", [point("only", 1)]);
    expect(canDeleteFromTarget(draft, target("status", [point("disk", 1)]), "only")).toBe(false);
    expect(canDeleteFromTarget(draft, target("status", []), "only")).toBe(true);
    expect(canDeleteFromTarget(draft, target("status", []), "only", true)).toBe(false);
  });
});
