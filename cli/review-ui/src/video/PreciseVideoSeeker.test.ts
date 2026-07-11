import { beforeEach, describe, expect, it, vi } from "vitest";
import { PreciseVideoSeeker, type PreviewState } from "./PreciseVideoSeeker.ts";

interface FakeVideo {
  video: HTMLVideoElement;
  setSeeking: (value: boolean) => void;
  setReadyState: (value: number) => void;
}

function fakeVideo(): FakeVideo {
  const video = document.createElement("video");
  let currentTime = 0;
  let seeking = false;
  let readyState = 1;
  Object.defineProperties(video, {
    currentTime: {
      configurable: true,
      get: () => currentTime,
      set: (value: number) => {
        currentTime = value;
      },
    },
    duration: { configurable: true, get: () => 10 },
    seeking: { configurable: true, get: () => seeking },
    readyState: { configurable: true, get: () => readyState },
  });
  return {
    video,
    setSeeking: (value) => {
      seeking = value;
    },
    setReadyState: (value) => {
      readyState = value;
    },
  };
}

describe("PreciseVideoSeeker", () => {
  beforeEach(() => vi.useFakeTimers());

  it("completes a same-position seek without waiting for seeked", async () => {
    const fake = fakeVideo();
    const states: PreviewState[] = [];
    const seeker = new PreciseVideoSeeker(fake.video, (state) => states.push(state));
    seeker.seek(0);
    await Promise.resolve();
    expect(states).toEqual([
      { status: "seeking", shownFrameTime: null, message: null },
      { status: "ready", shownFrameTime: null, message: null },
    ]);
  });

  it("cancels stale generations during rapid seeks", async () => {
    const fake = fakeVideo();
    fake.setSeeking(true);
    const states: PreviewState[] = [];
    const seeker = new PreciseVideoSeeker(fake.video, (state) => states.push(state));
    seeker.seek(1);
    seeker.seek(2);
    fake.setSeeking(false);
    fake.video.dispatchEvent(new Event("seeked"));
    await Promise.resolve();
    expect(fake.video.currentTime).toBe(2);
    expect(states.filter((state) => state.status === "ready")).toHaveLength(1);
  });

  it("ignores a cancelled frame callback and reports only the current mediaTime", async () => {
    const fake = fakeVideo();
    fake.setSeeking(true);
    const callbacks = new Map<number, VideoFrameRequestCallback>();
    const cancelled: number[] = [];
    let nextId = 0;
    Object.defineProperties(fake.video, {
      requestVideoFrameCallback: {
        configurable: true,
        value: (callback: VideoFrameRequestCallback) => {
          const id = ++nextId;
          callbacks.set(id, callback);
          return id;
        },
      },
      cancelVideoFrameCallback: {
        configurable: true,
        value: (id: number) => cancelled.push(id),
      },
    });
    const states: PreviewState[] = [];
    const seeker = new PreciseVideoSeeker(fake.video, (state) => states.push(state));
    seeker.seek(1);
    fake.setSeeking(false);
    fake.video.dispatchEvent(new Event("seeked"));
    await Promise.resolve();
    expect(callbacks.has(1)).toBe(true);

    fake.setSeeking(true);
    seeker.seek(2);
    expect(cancelled).toContain(1);
    callbacks.get(1)?.(0, { mediaTime: 1 } as VideoFrameCallbackMetadata);
    fake.setSeeking(false);
    fake.video.dispatchEvent(new Event("seeked"));
    await Promise.resolve();
    callbacks.get(2)?.(0, { mediaTime: 1.967 } as VideoFrameCallbackMetadata);

    expect(states.at(-1)).toEqual({
      status: "ready",
      shownFrameTime: 1.967,
      message: null,
    });
    expect(states.filter((state) => state.status === "ready")).toHaveLength(1);
  });

  it("watches for the presented frame before a paused seek completes", async () => {
    const fake = fakeVideo();
    fake.setSeeking(true);
    let callback: VideoFrameRequestCallback | null = null;
    Object.defineProperties(fake.video, {
      requestVideoFrameCallback: {
        configurable: true,
        value: (next: VideoFrameRequestCallback) => {
          callback = next;
          return 1;
        },
      },
      cancelVideoFrameCallback: {
        configurable: true,
        value: vi.fn(),
      },
    });
    const states: PreviewState[] = [];
    const seeker = new PreciseVideoSeeker(fake.video, (state) => states.push(state));

    seeker.seek(4);
    expect(callback).not.toBeNull();
    callback!(0, { mediaTime: 3.967 } as VideoFrameCallbackMetadata);
    expect(states.at(-1)?.status).toBe("seeking");

    fake.setSeeking(false);
    fake.video.dispatchEvent(new Event("seeked"));
    await Promise.resolve();
    expect(states.at(-1)).toEqual({
      status: "ready",
      shownFrameTime: 3.967,
      message: null,
    });
  });

  it("falls back after a qualifying seek when no frame callback arrives", async () => {
    const fake = fakeVideo();
    fake.setSeeking(true);
    Object.defineProperty(fake.video, "requestVideoFrameCallback", {
      configurable: true,
      value: () => 1,
    });
    Object.defineProperty(fake.video, "cancelVideoFrameCallback", {
      configurable: true,
      value: vi.fn(),
    });
    const states: PreviewState[] = [];
    const seeker = new PreciseVideoSeeker(fake.video, (state) => states.push(state));
    seeker.seek(3);
    fake.setSeeking(false);
    fake.video.dispatchEvent(new Event("seeked"));
    await Promise.resolve();
    vi.advanceTimersByTime(500);
    expect(states.at(-1)).toEqual({
      status: "ready",
      shownFrameTime: null,
      message: null,
    });
  });

  it("reaches an explicit timeout state when metadata never loads", () => {
    const fake = fakeVideo();
    fake.setReadyState(0);
    const states: PreviewState[] = [];
    const seeker = new PreciseVideoSeeker(fake.video, (state) => states.push(state));
    seeker.seek(4);
    vi.advanceTimersByTime(5_000);
    expect(states.at(-1)).toMatchObject({ status: "unavailable" });
  });

  it("terminates on a media error", () => {
    const fake = fakeVideo();
    fake.setSeeking(true);
    const states: PreviewState[] = [];
    const seeker = new PreciseVideoSeeker(fake.video, (state) => states.push(state));
    seeker.seek(1);
    fake.video.dispatchEvent(new Event("error"));
    expect(states.at(-1)).toMatchObject({
      status: "unavailable",
      message: "The browser could not present this video preview.",
    });
  });

  it("detects a media error that happened before seeker listeners were attached", () => {
    const fake = fakeVideo();
    Object.defineProperty(fake.video, "error", {
      configurable: true,
      value: { code: 4 },
    });
    const states: PreviewState[] = [];
    const seeker = new PreciseVideoSeeker(fake.video, (state) => states.push(state));
    seeker.seek(1);
    vi.advanceTimersByTime(5_000);
    expect(states).toEqual([
      { status: "seeking", shownFrameTime: null, message: null },
      {
        status: "unavailable",
        shownFrameTime: null,
        message: "The browser could not present this video preview.",
      },
    ]);
  });
});
