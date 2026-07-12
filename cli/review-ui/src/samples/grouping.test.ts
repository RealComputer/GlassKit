import { describe, expect, it } from "vitest";
import { sample } from "../test/fixtures.ts";
import { groupConsecutiveSamples, regularSampleInterval } from "./grouping.ts";

describe("sample table grouping", () => {
  it("groups only consecutive samples with the same editable settings", () => {
    const groups = groupConsecutiveSamples([
      sample("false-1", 0, "false"),
      sample("false-2", 0.5, "false"),
      sample("true", 1, "true"),
      sample("false-3", 1.5, "false"),
    ]);

    expect(groups.map((group) => group.samples.map((item) => item.id))).toEqual([
      ["false-1", "false-2"],
      ["true"],
      ["false-3"],
    ]);
  });

  it("ignores serialization origin but keeps other sample settings distinct", () => {
    const first = sample("first", 0, "true");
    const second = sample("second", 0.5, "true");
    second.origin = { block_index: 1, kind: "range", every_s: 0.5 };
    const commented = { ...sample("commented", 1, "true"), comment: "Check this" };

    expect(
      groupConsecutiveSamples([first, second, commented]).map((group) => group.samples.length),
    ).toEqual([2, 1]);
  });

  it("reports a cadence only when three or more timestamps are regular", () => {
    expect(regularSampleInterval([sample("one", 0), sample("two", 0.5), sample("three", 1)])).toBe(
      0.5,
    );
    expect(
      regularSampleInterval([sample("one", 0), sample("two", 0.5), sample("three", 1.25)]),
    ).toBeNull();
    expect(regularSampleInterval([sample("one", 0), sample("two", 0.5)])).toBeNull();
  });

  it("keeps distinct integers beyond JavaScript's safe range in separate groups", () => {
    const groups = groupConsecutiveSamples([
      sample("first", 0, "9007199254740992"),
      sample("second", 0.5, "9007199254740993"),
    ]);

    expect(groups.map((group) => group.samples.map((item) => item.id))).toEqual([
      ["first"],
      ["second"],
    ]);
  });
});
