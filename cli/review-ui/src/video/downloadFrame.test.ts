import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadVideoFrame, frameDownloadFilename } from "./downloadFrame.ts";

afterEach(() => vi.restoreAllMocks());

describe("frameDownloadFilename", () => {
  it("uses only the case name and timestamp", () => {
    expect(frameDownloadFilename("full run/one", 39.1414)).toBe("full-run-one-39.141s.png");
  });

  it("falls back safely for an unusable case name or timestamp", () => {
    expect(frameDownloadFilename("...", Number.NaN)).toBe("frame-0.000s.png");
  });
});

describe("downloadVideoFrame", () => {
  it("downloads the presented frame as a native-resolution PNG", async () => {
    const video = document.createElement("video");
    Object.defineProperties(video, {
      readyState: { configurable: true, value: HTMLMediaElement.HAVE_CURRENT_DATA },
      seeking: { configurable: true, value: false },
      videoWidth: { configurable: true, value: 640 },
      videoHeight: { configurable: true, value: 480 },
    });
    const drawImage = vi.fn();
    const blob = new Blob(["png"], { type: "image/png" });
    const createElement = document.createElement.bind(document);
    let canvas!: HTMLCanvasElement;
    let link!: HTMLAnchorElement;
    vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
      const element = createElement(tagName, options);
      if (tagName === "canvas") {
        canvas = element as HTMLCanvasElement;
        vi.spyOn(canvas, "getContext").mockReturnValue({ drawImage } as never);
        vi.spyOn(canvas, "toBlob").mockImplementation((callback) => callback(blob));
      } else if (tagName === "a") {
        link = element as HTMLAnchorElement;
        vi.spyOn(link, "click").mockImplementation(() => undefined);
      }
      return element;
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:frame");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    await downloadVideoFrame(video, "case-1.000s.png");

    expect(canvas.width).toBe(640);
    expect(canvas.height).toBe(480);
    expect(drawImage).toHaveBeenCalledWith(video, 0, 0, 640, 480);
    expect(link.download).toBe("case-1.000s.png");
    expect(link.href).toBe("blob:frame");
    expect(link.click).toHaveBeenCalledOnce();
  });

  it("rejects a frame that is not ready", async () => {
    const video = document.createElement("video");
    Object.defineProperties(video, {
      readyState: { configurable: true, value: HTMLMediaElement.HAVE_METADATA },
      seeking: { configurable: true, value: false },
      videoWidth: { configurable: true, value: 640 },
      videoHeight: { configurable: true, value: 480 },
    });

    await expect(downloadVideoFrame(video, "frame.png")).rejects.toThrow("not ready to download");
  });
});
