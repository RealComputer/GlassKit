import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchAuthoritativeFrame, ReviewApiError } from "./client.ts";

afterEach(() => vi.unstubAllGlobals());

describe("fetchAuthoritativeFrame", () => {
  it("requests a canonical time and returns the frame identity", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(new Blob(["png"], { type: "image/png" }), {
          headers: {
            "Content-Type": "image/png",
            "X-GlassKit-Requested-Time": "1.23",
            "X-GlassKit-Media-Time": "1.2",
            "X-GlassKit-Frame-Index": "12",
            "X-GlassKit-Frame-SHA256": "sha256-pixels",
          },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const frame = await fetchAuthoritativeFrame(
      "/api/case-files/case.yaml/frame",
      1.2300000004,
      controller.signal,
      { clientId: "video-panel-1", generation: 4 },
    );

    expect(fetchMock).toHaveBeenCalledWith("/api/case-files/case.yaml/frame?at=1.23", {
      headers: {
        Accept: "image/png",
        "X-GlassKit-Frame-Client": "video-panel-1",
        "X-GlassKit-Frame-Generation": "4",
      },
      signal: controller.signal,
    });
    expect(frame).toMatchObject({
      requestedTime: 1.23,
      mediaTime: 1.2,
      frameIndex: 12,
      sha256: "sha256-pixels",
    });
    expect(frame.image.type).toBe("image/png");
  });

  it("accepts a seek response without a global frame index", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(new Blob(["png"], { type: "image/png" }), {
            headers: {
              "Content-Type": "image/png",
              "X-GlassKit-Requested-Time": "1.23",
              "X-GlassKit-Media-Time": "1.2",
              "X-GlassKit-Frame-SHA256": "sha256-pixels",
            },
          }),
        ),
      ),
    );

    await expect(fetchAuthoritativeFrame("/frame", 1.23)).resolves.toMatchObject({
      frameIndex: null,
      mediaTime: 1.2,
    });
  });

  it("preserves structured API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              error: {
                code: "invalid_frame_time",
                message: "Frame time is invalid.",
                details: [],
              },
            }),
            { status: 400, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );

    await expect(fetchAuthoritativeFrame("/frame", 1)).rejects.toEqual(
      expect.objectContaining<Partial<ReviewApiError>>({
        code: "invalid_frame_time",
        message: "Frame time is invalid.",
      }),
    );
  });
});
