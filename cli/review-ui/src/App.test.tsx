import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App.tsx";
import { caseFile, sample, evalDirectory, target } from "./test/fixtures.ts";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("review application navigation and drafts", () => {
  it("uses the unobstructed video surface to toggle playback", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    await screen.findByLabelText("Review transport");
    const video = document.querySelector("video");
    expect(video).not.toBeNull();
    expect(video?.controls).toBe(false);
    expect(video?.muted).toBe(true);

    const play = vi.spyOn(video!, "play").mockResolvedValue();
    const pause = vi.spyOn(video!, "pause").mockImplementation(() => undefined);
    Object.defineProperty(video, "paused", { configurable: true, value: true });
    fireEvent.click(video!);
    expect(play).toHaveBeenCalledOnce();

    Object.defineProperty(video, "paused", { configurable: true, value: false });
    pause.mockClear();
    fireEvent.click(video!);
    expect(pause).toHaveBeenCalledOnce();
  });

  it("gives transport actions visible labels and shortcut hints", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const transport = await screen.findByLabelText("Review transport");
    const groups = within(transport).getAllByRole("group");
    expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
      "Sample navigation",
      "Video controls",
      "Sample creation",
    ]);

    const sampleNavigation = within(transport).getByRole("group", { name: "Sample navigation" });
    const previous = within(sampleNavigation).getByRole("button", { name: "Previous sample" });
    const next = within(sampleNavigation).getByRole("button", { name: "Next sample" });
    expect(previous.textContent).toContain("Previous sample");
    expect(previous.textContent).toContain("[");
    expect(next.textContent).toContain("Next sample");
    expect(next.textContent).toContain("]");

    const videoControls = within(transport).getByRole("group", { name: "Video controls" });
    const backward = within(videoControls).getByRole("button", {
      name: "Move video time back 0.1 seconds",
    });
    const forward = within(videoControls).getByRole("button", {
      name: "Move video time forward 0.1 seconds",
    });
    expect(backward.textContent).toContain("−0.1 s");
    expect(backward.textContent).toContain("←");
    expect(forward.textContent).toContain("+0.1 s");
    expect(forward.textContent).toContain("→");
    expect(within(videoControls).getByRole("button", { name: "Play video" })).toBeTruthy();
    expect(within(videoControls).getByLabelText("Time")).toBeTruthy();
    expect(within(videoControls).getByLabelText("Playback rate")).toBeTruthy();
    expect(
      within(videoControls).getByRole("button", { name: "Download current frame" }),
    ).toBeTruthy();

    const sampleCreation = within(transport).getByRole("group", { name: "Sample creation" });
    expect(within(sampleCreation).getByRole("button", { name: /Add sample/ })).toBeTruthy();
    expect(screen.queryByText("Sample 1.000s")).toBeNull();
    expect(document.querySelector(".header-context")?.textContent).toBe("case-001 / target_a");
  });

  it("shows the selected case video path without a details disclosure", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    expect(await screen.findByText("fixture.mp4")).toBeTruthy();
    const sidebar = screen.getByLabelText("Eval navigation");
    expect(
      within(sidebar)
        .getAllByRole("heading")
        .map((heading) => heading.textContent),
    ).toEqual(["Cases", "Targets", "Sources"]);
    expect(screen.queryByText("Case details")).toBeNull();
    expect(screen.getAllByText("A fixture case")).toHaveLength(1);
    expect(within(sidebar).getByRole("button", { name: "Case file" })).toBeTruthy();
    expect(within(sidebar).getByRole("button", { name: "Eval config file" })).toBeTruthy();
  });

  it("opens purpose-named source drawers without a redundant read-only subtitle", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    await screen.findByText("fixture.mp4");
    fireEvent.click(screen.getByRole("button", { name: "Case file" }));
    expect(screen.getByRole("heading", { name: "Case file" })).toBeTruthy();
    expect(screen.queryByText("Read-only source")).toBeNull();
    fireEvent.click(screen.getByLabelText("Close source drawer"));

    fireEvent.click(screen.getByRole("button", { name: "Eval config file" }));
    expect(screen.getByRole("heading", { name: "Eval config file" })).toBeTruthy();
    expect(screen.queryByText("Read-only source")).toBeNull();
  });

  it("disables adding a sample when the video time already has one", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const add = await screen.findByRole("button", { name: /Add sample/ });
    expect(add).toHaveProperty("disabled", true);
    expect(add.getAttribute("title")).toBe("A sample already exists at this time");

    fireEvent.click(screen.getByRole("button", { name: "Move video time forward 0.1 seconds" }));

    await waitFor(() => expect(add).toHaveProperty("disabled", false));
    expect(add.getAttribute("title")).toBe("Add sample at video time (A)");
  });

  it("switches between timeline and source-agnostic grouped samples", async () => {
    const rangedTarget = target("status", [sample("first", 1), sample("second", 1.5)]);
    rangedTarget.samples[1].origin = { block_index: 1, kind: "range", every_s: 0.5 };
    rangedTarget.display_groups = [
      {
        id: "range-group",
        kind: "range",
        sample_ids: ["first", "second"],
        start_s: 1,
        end_s: 2,
        every_s: 0.5,
        timestamps_s: [1, 1.5],
      },
    ];
    const doc = caseFile([rangedTarget]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const timelineTab = await screen.findByRole("tab", { name: "Timeline" });
    const samplesTab = screen.getByRole("tab", { name: "Samples" });
    const fit = await screen.findByRole("button", { name: "Fit" });
    expect(timelineTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe("timeline-view-tab");
    expect(timelineTab.closest(".review-view-toolbar")).toBe(fit.closest(".review-view-toolbar"));
    expect(screen.getByRole("tablist").contains(fit)).toBe(false);
    timelineTab.focus();
    fireEvent.pointerUp(timelineTab);
    expect(document.activeElement).toBe(document.body);
    const first = screen.getByRole("button", {
      name: "status, 1.000s, expected false",
    });
    const second = screen.getByRole("button", {
      name: "status, 1.500s, expected false",
    });
    expect(document.querySelector(".range-band")).toBeNull();
    expect(first.style.getPropertyValue("--expect-color")).toBe(
      second.style.getPropertyValue("--expect-color"),
    );
    expect(screen.queryByText("Part of a range")).toBeNull();

    fireEvent.keyDown(timelineTab, { key: "ArrowRight" });
    expect(timelineTab.getAttribute("aria-selected")).toBe("true");
    expect(samplesTab.getAttribute("aria-selected")).toBe("false");
    expect(screen.getByLabelText("Time")).toHaveProperty("value", "1.100");

    fireEvent.click(samplesTab);
    expect(samplesTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByLabelText("Sample timeline")).toBeNull();
    const group = screen.getByRole("button", {
      name: "Expand 1.000s–1.500s · 2 samples",
    });
    expect(screen.getByRole("table").querySelectorAll("tbody tr")).toHaveLength(1);

    fireEvent.click(group);
    expect(document.querySelectorAll(".sample-group-member")).toHaveLength(2);
    expect(screen.queryByText("Same settings as group")).toBeNull();
    expect(screen.getByRole("table").querySelectorAll("tbody tr")).toHaveLength(3);
    expect(screen.queryByText("Part of a range")).toBeNull();
  });

  it("shows an immediate timestamp and expectation tooltip over timeline samples", async () => {
    const doc = caseFile([
      target("target_a", [sample("first", 1, "false"), sample("second", 2, "true")]),
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const first = await screen.findByRole("button", {
      name: "target a, 1.000s, expected false",
    });
    expect(first.getAttribute("title")).toBeNull();
    const lane = document.querySelector<HTMLElement>(".lane-track");
    expect(lane).not.toBeNull();
    vi.spyOn(lane!, "getBoundingClientRect").mockReturnValue({
      bottom: 52,
      height: 52,
      left: 0,
      right: 1000,
      top: 0,
      width: 1000,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });

    fireEvent.pointerMove(lane!, { clientX: 100, clientY: 40, pointerId: 1 });
    expect(screen.getByRole("tooltip").textContent).toBe("1.000s · false");
    fireEvent.pointerMove(lane!, { clientX: 200, clientY: 40, pointerId: 1 });
    expect(screen.getByRole("tooltip").textContent).toBe("2.000s · true");
    const timelineScroll = document.querySelector<HTMLElement>(".timeline-scroll");
    expect(timelineScroll).not.toBeNull();
    fireEvent.scroll(timelineScroll!);
    expect(screen.queryByRole("tooltip")).toBeNull();

    fireEvent.pointerMove(lane!, { clientX: 100, clientY: 40, pointerId: 1 });
    expect(screen.getByRole("tooltip").textContent).toBe("1.000s · false");
    fireEvent.pointerLeave(lane!);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("omits range context for an individual sample", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    await screen.findByLabelText("Sample inspector");
    expect(screen.queryByText("Individual samples")).toBeNull();
    expect(document.querySelector(".derived-group")).toBeNull();
  });

  it("scrubs the video by dragging across the timeline", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const playhead = await screen.findByRole("slider", { name: "Video playhead" });
    vi.spyOn(playhead, "getBoundingClientRect").mockReturnValue({
      bottom: 30,
      height: 30,
      left: 100,
      right: 1100,
      top: 0,
      width: 1000,
      x: 100,
      y: 0,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(playhead, { button: 0, clientX: 300, pointerId: 1 });
    fireEvent.pointerMove(playhead, { clientX: 800, pointerId: 1 });
    fireEvent.pointerUp(playhead, { button: 0, clientX: 800, pointerId: 1 });

    await waitFor(() => expect(screen.getByLabelText("Time")).toHaveProperty("value", "7.000"));
    expect(playhead.getAttribute("aria-valuenow")).toBe("7");
  });

  it("keeps repeating navigation shortcuts available after a timeline sample receives focus", async () => {
    const doc = caseFile([
      target("target_a", [
        sample("first", 1, "1"),
        sample("second", 2, "2"),
        sample("third", 3, "3"),
      ]),
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const first = await screen.findByRole("button", {
      name: "target a, 1.000s, expected 1",
    });
    first.focus();
    fireEvent.pointerUp(first);
    expect(document.activeElement).toBe(document.body);

    first.focus();
    fireEvent.keyDown(first, { key: "]" });
    await waitFor(() => expect(screen.getByLabelText("Timestamp")).toHaveProperty("value", "2"));

    fireEvent.keyDown(first, { key: "]", repeat: true });
    await waitFor(() => expect(screen.getByLabelText("Timestamp")).toHaveProperty("value", "3"));

    fireEvent.keyDown(first, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByLabelText("Time")).toHaveProperty("value", "3.100"));
  });

  it("keeps the fit timeline's final label inside its viewport", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const fit = await screen.findByRole("button", { name: "Fit" });
    const scroll = document.querySelector(".timeline-scroll");
    const finalTick = document.querySelector<HTMLElement>(".ruler-tick:last-child");

    expect(scroll?.classList.contains("fit")).toBe(true);
    expect(finalTick?.style.right).toBe("0px");
    expect(finalTick?.style.left).toBe("");

    fireEvent.click(screen.getByRole("button", { name: "2×" }));
    expect(fit.classList.contains("selected")).toBe(false);
    expect(scroll?.classList.contains("fit")).toBe(false);
  });

  it("gives form fields unique identifiers and associates labels with controls", async () => {
    const doc = caseFile();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    await screen.findByRole("group", { name: "Expected value" });
    const fields = Array.from(
      document.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
        "input, select, textarea",
      ),
    );
    const ids = fields.map((field) => field.id).filter(Boolean);

    expect(fields.length).toBeGreaterThan(0);
    expect(fields.every((field) => Boolean(field.id || field.name))).toBe(true);
    expect(new Set(ids).size).toBe(ids.length);
    for (const label of document.querySelectorAll<HTMLLabelElement>("label[for]")) {
      const control = document.getElementById(label.htmlFor);
      expect(control?.matches("input, select, textarea")).toBe(true);
    }
  });

  it("keeps an invalid partial expectation selected during blur and sample navigation", async () => {
    const doc = caseFile([
      target("numeric_target", [sample("first", 1, "1"), sample("second", 2, "2")]),
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const expected = await screen.findByLabelText("Expected value");
    await waitFor(() => expect(expected).toHaveProperty("value", "1"));
    fireEvent.change(expected, { target: { value: "-" } });
    fireEvent.blur(expected);
    fireEvent.click(screen.getByRole("tab", { name: "Samples" }));
    const secondRow = screen
      .getAllByText("2.000s")
      .find((element) => element.tagName === "TD")
      ?.closest("tr");
    expect(secondRow).not.toBeNull();
    fireEvent.click(secondRow!);

    expect(screen.getByLabelText("Timestamp")).toHaveProperty("value", "1");
    expect(screen.getByText("Fix errors")).toBeTruthy();
    expect(screen.getByText("Enter a valid JSON number.")).toBeTruthy();
  });

  it("keeps a backend-tolerated near-end timestamp valid on blur", async () => {
    const doc = caseFile([target("near_end", [sample("end", 10.01, "1")])]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const timestamp = await screen.findByLabelText("Timestamp");
    await waitFor(() => expect(timestamp).toHaveProperty("value", "10.01"));
    fireEvent.focus(timestamp);
    fireEvent.blur(timestamp);

    expect(screen.queryByText(/Time must not exceed/)).toBeNull();
    expect(screen.queryByText("Fix errors")).toBeNull();
  });

  it("blocks adding a sample while the selected field draft is invalid", async () => {
    const doc = caseFile([target("numeric_target", [sample("first", 1, "1")])]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const transportTime = await screen.findByLabelText("Time");
    await waitFor(() => expect(transportTime).toHaveProperty("value", "1.000"));
    fireEvent.change(transportTime, { target: { value: "3" } });
    fireEvent.keyDown(transportTime, { key: "Enter" });
    const expected = screen.getByLabelText("Expected value");
    fireEvent.change(expected, { target: { value: "-" } });
    fireEvent.blur(expected);

    fireEvent.click(screen.getByRole("tab", { name: "Samples" }));

    const add = screen.getByRole("button", { name: /Add sample/ });
    expect(add).toHaveProperty("disabled", true);
    fireEvent.click(add);
    fireEvent.keyDown(window, { key: "a" });

    expect(screen.getByRole("table").querySelectorAll("tbody tr")).toHaveLength(1);
    expect(expected).toHaveProperty("value", "-");
    expect(screen.getByText("Enter a valid JSON number.")).toBeTruthy();
  });

  it("clears a deleted sample draft error before selecting its neighbor", async () => {
    const doc = caseFile([
      target("numeric_target", [sample("first", 1, "1"), sample("second", 2, "2")]),
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          const payload = JSON.parse(String(init.body)) as {
            targets: { numeric_target: { samples: ReturnType<typeof sample>[] } };
          };
          return Promise.resolve(
            response({
              ...doc,
              revision: "deleted-first",
              targets: [target("numeric_target", payload.targets.numeric_target.samples)],
            }),
          );
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const expected = await screen.findByLabelText("Expected value");
    await waitFor(() => expect(expected).toHaveProperty("value", "1"));
    fireEvent.change(expected, { target: { value: "-" } });
    fireEvent.blur(expected);
    fireEvent.click(screen.getByRole("tab", { name: "Samples" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete sample" }));

    await waitFor(() =>
      expect(screen.getByLabelText("Expected value")).toHaveProperty("value", "2"),
    );
    expect(screen.getByRole("table").querySelectorAll("tbody tr")).toHaveLength(1);
    expect(screen.queryByText("Fix errors")).toBeNull();
  });

  it("treats a whitespace-only optional field as an unchanged null value", async () => {
    const doc = caseFile([target("target_a", [sample("first", 1, "true")])]);
    let putCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          putCount += 1;
          return Promise.resolve(response(doc));
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    const field = await screen.findByLabelText(/Field/);
    expect(field.getAttribute("placeholder")).toBeNull();
    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.blur(field);
    await new Promise((resolve) => window.setTimeout(resolve, 450));

    expect(putCount).toBe(0);
  });

  it("commits human-entered transport time only on Enter", async () => {
    const doc = caseFile([target("target_a", [sample("first", 1, "true")])]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    const time = await screen.findByLabelText("Time");
    await waitFor(() => expect(time).toHaveProperty("value", "1.000"));
    fireEvent.focus(time);
    fireEvent.change(time, { target: { value: "1.234" } });
    expect(time).toHaveProperty("value", "1.234");
    fireEvent.keyDown(time, { key: "Enter" });
    expect(time).toHaveProperty("value", "1.234");
  });

  it("suppresses shortcuts inside overlays, traps focus, and restores the opener", async () => {
    const doc = caseFile([target("target_a", [sample("first", 1, "true")])]);
    let putCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          putCount += 1;
          return Promise.resolve(response(doc));
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    const time = await screen.findByLabelText("Time");
    fireEvent.focus(time);
    fireEvent.change(time, { target: { value: "1.234" } });
    fireEvent.keyDown(time, { key: "Enter" });

    const opener = screen.getByLabelText("Show keyboard shortcuts");
    opener.focus();
    fireEvent.click(opener);
    const close = await screen.findByLabelText("Close keyboard shortcuts");
    await waitFor(() => expect(document.activeElement).toBe(close));
    fireEvent.keyDown(window, { key: "a" });
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    fireEvent.click(close);
    await waitFor(() => expect(document.activeElement).toBe(opener));

    const sourceOpener = screen.getByText("Case file");
    sourceOpener.focus();
    fireEvent.click(sourceOpener);
    await screen.findByLabelText("Close source drawer");
    fireEvent.keyDown(window, { key: "a" });
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(sourceOpener));
    await new Promise((resolve) => window.setTimeout(resolve, 450));

    expect(putCount).toBe(0);
  });

  it("does not dirty unchanged inspector fields on blur", async () => {
    const unchangedSample = {
      ...sample("first", 1, "1"),
      field: "confidence",
      comment: "No change",
      compare: { mode: "numeric" as const, tolerance: 0.1 },
    };
    const doc = caseFile([target("numeric_target", [unchangedSample])]);
    let putCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          putCount += 1;
          return Promise.resolve(response(doc));
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    const controls = await Promise.all([
      screen.findByLabelText("Timestamp"),
      screen.findByLabelText("Expected value"),
      screen.findByLabelText(/Field/),
      screen.findByLabelText("Tolerance"),
      screen.findByLabelText("Comment optional"),
    ]);
    await waitFor(() => expect(controls[1]).toHaveProperty("value", "1"));
    for (const control of controls) {
      fireEvent.focus(control);
      fireEvent.blur(control);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 450));

    expect(putCount).toBe(0);
  });

  it("keeps an invalid expectation draft visible across an older PUT response", async () => {
    const doc = caseFile([target("numeric_target", [sample("first", 1, "1")])]);
    let resolvePut!: (response: Response) => void;
    const put = new Promise<Response>((resolve) => {
      resolvePut = resolve;
    });
    let putStarted = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          putStarted = true;
          return put;
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    const comment = await screen.findByLabelText("Comment optional");
    fireEvent.change(comment, { target: { value: "Save this first" } });
    fireEvent.blur(comment);
    await waitFor(() => expect(putStarted).toBe(true));
    const expected = screen.getByLabelText("Expected value");
    fireEvent.change(expected, { target: { value: "-" } });
    const accepted = {
      ...doc,
      revision: "accepted-comment",
      targets: [
        target("numeric_target", [{ ...sample("first", 1, "1"), comment: "Save this first" }]),
      ],
    };
    resolvePut(response(accepted));
    await waitFor(() => expect(screen.getByText("Fix errors")).toBeTruthy());

    expect(expected).toHaveProperty("value", "-");
    expect(screen.getByText("Enter a valid JSON number.")).toBeTruthy();
  });

  it("offers an explicit discard path for an invalid draft", async () => {
    const doc = caseFile([target("numeric_target", [sample("first", 1, "1")])]);
    let gets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) {
          gets += 1;
          return Promise.resolve(response({ ...doc }));
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    const expected = await screen.findByLabelText("Expected value");
    await waitFor(() => expect(expected).toHaveProperty("value", "1"));
    fireEvent.change(expected, { target: { value: "-" } });
    fireEvent.click(await screen.findByText("Discard drafts"));
    await waitFor(() => expect(expected).toHaveProperty("value", "1"));

    expect(gets).toBe(2);
    expect(screen.queryByText("Fix errors")).toBeNull();
  });

  it("recreates the media element when a disk reload keeps the same video URL", async () => {
    const original = caseFile([target("numeric_target", [sample("first", 1, "1")])]);
    const reloaded = {
      ...original,
      revision: "replacement-video",
      video: original.video ? { ...original.video, display_path: "replacement.mp4" } : null,
    };
    let gets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("/api/case-files/")) {
          gets += 1;
          return Promise.resolve(response(gets === 1 ? original : reloaded));
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const expected = await screen.findByLabelText("Expected value");
    const firstVideo = document.querySelector("video");
    expect(firstVideo).not.toBeNull();
    fireEvent.change(expected, { target: { value: "-" } });
    fireEvent.click(screen.getByText("Discard drafts"));

    await waitFor(() => expect(gets).toBe(2));
    await waitFor(() => expect(document.querySelector("video")).not.toBe(firstVideo));
    expect(document.querySelector("video")?.getAttribute("src")).toBe(original.video?.url);
  });

  it("shows a save failure message when the backend returns no details", async () => {
    const doc = caseFile([target("target_a", [sample("first", 1, "true")])]);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          return Promise.resolve(
            response(
              {
                error: {
                  code: "write_failed",
                  message: "The case file is read-only.",
                  details: [],
                },
              },
              500,
            ),
          );
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(doc));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    const comment = await screen.findByLabelText("Comment optional");
    fireEvent.change(comment, { target: { value: "Trigger a save" } });
    fireEvent.blur(comment);

    expect(await screen.findByText("The case file is read-only.")).toBeTruthy();
    expect(screen.getByText("Save failed")).toBeTruthy();
  });
});
