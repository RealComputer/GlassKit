import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadFrameUrl, frameDownloadFilename } from "./downloadFrame.ts";

afterEach(() => vi.restoreAllMocks());

describe("frameDownloadFilename", () => {
  it("uses only the case name and timestamp", () => {
    expect(frameDownloadFilename("full run/one", 39.1414)).toBe("full-run-one-39.141s.png");
  });

  it("falls back safely for an unusable case name or timestamp", () => {
    expect(frameDownloadFilename("...", Number.NaN)).toBe("frame-0.000s.png");
  });
});

describe("downloadFrameUrl", () => {
  it("downloads the authoritative frame with the requested filename", () => {
    const createElement = document.createElement.bind(document);
    let link!: HTMLAnchorElement;
    vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
      const element = createElement(tagName, options);
      if (tagName === "a") {
        link = element as HTMLAnchorElement;
        vi.spyOn(link, "click").mockImplementation(() => undefined);
      }
      return element;
    });

    downloadFrameUrl("blob:exact-frame", "case-1.000s.png");

    expect(link.download).toBe("case-1.000s.png");
    expect(link.href).toBe("blob:exact-frame");
    expect(link.click).toHaveBeenCalledOnce();
  });
});
