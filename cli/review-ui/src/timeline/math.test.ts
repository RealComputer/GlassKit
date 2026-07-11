import { describe, expect, it } from "vitest";
import {
  anchoredScrollLeft,
  markerSelector,
  positionToTime,
  rulerTicks,
  timelineTrackWidth,
  timeToPosition,
} from "./math.ts";

describe("timeline math", () => {
  it("maps and clamps time positions", () => {
    expect(timeToPosition(5, 20)).toBe(0.25);
    expect(timeToPosition(-1, 20)).toBe(0);
    expect(positionToTime(2, 20)).toBe(20);
  });

  it("grows the track at zoom levels and keeps the anchor in place", () => {
    const oldWidth = timelineTrackWidth(948, 1);
    const nextWidth = timelineTrackWidth(948, 4);
    const nextScroll = anchoredScrollLeft(0, 800, oldWidth, nextWidth, 0.5);
    expect(oldWidth).toBe(800);
    expect(nextWidth).toBe(3200);
    expect(nextScroll).toBe(1200);
  });

  it("generates stable human-scale ruler ticks including duration", () => {
    const ticks = rulerTicks(18.2, 1);
    expect(ticks[0]).toBe(0);
    expect(ticks.at(-1)).toBe(18.2);
    expect(ticks.length).toBeGreaterThan(4);
  });

  it("scopes repeated sample IDs to their target lane", () => {
    document.body.innerHTML = `
      <button data-target-id="first" data-sample-id="block-0-sample-0"></button>
      <button data-target-id="second" data-sample-id="block-0-sample-0"></button>
    `;
    const selected = document.querySelector(markerSelector("second", "block-0-sample-0"));
    expect(selected?.getAttribute("data-target-id")).toBe("second");
  });
});
