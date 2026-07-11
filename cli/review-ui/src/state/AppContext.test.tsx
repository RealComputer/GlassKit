import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CaseFileDocument } from "../api/types.ts";
import { caseFile, sample, evalDirectory, target } from "../test/fixtures.ts";
import { AppProvider, useApp } from "./AppContext.tsx";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function Harness() {
  const { state, updateSample, reloadFromDisk, flushCurrentCase, selectCase } = useApp();
  const [flushed, setFlushed] = useState("idle");
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const currentSample = workspace?.document.targets[0]?.samples[0];
  return (
    <div>
      <output data-testid="source">{workspace?.document.case_file_source}</output>
      <output data-testid="time">{currentSample?.timestamp_s}</output>
      <output data-testid="phase">{workspace?.savePhase}</output>
      <output data-testid="flushed">{flushed}</output>
      <output data-testid="selected-case">{state.selectedCaseId}</output>
      <output data-testid="selected-target">{state.selectedTargetId}</output>
      <output data-testid="video-time">{state.video.currentTime}</output>
      <button
        type="button"
        onClick={() =>
          currentSample && updateSample("target_a", currentSample.id, { timestamp_s: 2 }, true)
        }
      >
        Edit two
      </button>
      <button
        type="button"
        onClick={() =>
          currentSample && updateSample("target_a", currentSample.id, { timestamp_s: 3 }, true)
        }
      >
        Edit three
      </button>
      <button type="button" onClick={() => void reloadFromDisk()}>
        Reload
      </button>
      <button
        type="button"
        onClick={() => void flushCurrentCase().then((ok) => setFlushed(String(ok)))}
      >
        Flush
      </button>
      <button type="button" onClick={() => void selectCase("case-002.yaml")}>
        Switch case
      </button>
    </div>
  );
}

function renderHarness() {
  return render(
    <AppProvider>
      <Harness />
    </AppProvider>,
  );
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("case save queue", () => {
  it("keeps a later-selected case active when the earlier GET resolves last", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const firstDocument = {
      ...caseFile([target("first_target", [sample("first-sample", 2)])]),
      id: "case-001.yaml",
      name: "case-001",
    };
    const secondDocument = {
      ...caseFile([target("second_target", [sample("second-sample", 7)])]),
      id: "case-002.yaml",
      name: "case-002",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (url.includes("case-001.yaml")) return first.promise;
        if (url.includes("case-002.yaml")) return second.promise;
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    renderHarness();
    await screen.findByText("case-001.yaml");
    fireEvent.click(screen.getByText("Switch case"));
    second.resolve(response(secondDocument));
    await screen.findByText("second_target");
    first.resolve(response(firstDocument));
    await new Promise((resolve) => window.setTimeout(resolve, 10));

    expect(screen.getByTestId("selected-case").textContent).toBe("case-002.yaml");
    expect(screen.getByTestId("selected-target").textContent).toBe("second_target");
    expect(screen.getByTestId("video-time").textContent).toBe("7");
  });

  it("invalidates a late PUT response after reload from disk", async () => {
    const original = { ...caseFile([target("target_a")]), case_file_source: "original" };
    const reloaded = {
      ...caseFile([target("target_a", [sample("target_a-sample", 1, "true")])]),
      case_file_source: "reloaded",
      revision: "reload-revision",
    };
    const late = {
      ...caseFile([target("target_a", [sample("target_a-sample", 2)])]),
      case_file_source: "late response",
      revision: "late-revision",
    };
    const put = deferred<Response>();
    let caseGets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") return put.promise;
        if (url.includes("/api/case-files/")) {
          caseGets += 1;
          return Promise.resolve(response(caseGets === 1 ? original : reloaded));
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    renderHarness();
    await screen.findByText("original");
    fireEvent.click(screen.getByText("Edit two"));
    await waitFor(() => expect(screen.getByTestId("phase").textContent).toBe("saving"));
    fireEvent.click(screen.getByText("Reload"));
    expect(caseGets).toBe(1);
    put.resolve(response(late));
    await screen.findByText("reloaded");

    expect(screen.getByTestId("source").textContent).toBe("reloaded");
    expect(screen.getByTestId("time").textContent).toBe("1");
  });

  it("flushes a newer version after an older in-flight save before resolving", async () => {
    const original = caseFile([target("target_a")]);
    const first = deferred<Response>();
    const second = deferred<Response>();
    const putBodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          putBodies.push(JSON.parse(String(init.body)) as unknown);
          return putBodies.length === 1 ? first.promise : second.promise;
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(original));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    renderHarness();
    await screen.findByText("video: fixture.mp4");
    fireEvent.click(screen.getByText("Edit two"));
    await waitFor(() => expect(putBodies).toHaveLength(1));
    fireEvent.click(screen.getByText("Edit three"));
    fireEvent.click(screen.getByText("Flush"));

    const acceptedTwo: CaseFileDocument = {
      ...original,
      targets: [target("target_a", [sample("target_a-sample", 2)])],
      revision: "accepted-two",
    };
    first.resolve(response(acceptedTwo));
    await waitFor(() => expect(putBodies).toHaveLength(2));
    expect(putBodies[1]).toMatchObject({
      targets: { target_a: { samples: [{ timestamp_s: 3 }] } },
    });
    const acceptedThree: CaseFileDocument = {
      ...original,
      targets: [target("target_a", [sample("target_a-sample", 3)])],
      revision: "accepted-three",
    };
    second.resolve(response(acceptedThree));

    await waitFor(() => expect(screen.getByTestId("flushed").textContent).toBe("true"));
    expect(screen.getByTestId("time").textContent).toBe("3");
    expect(screen.getByTestId("phase").textContent).toBe("saved");
  });

  it("does not continue an in-flight save queue after unmount", async () => {
    const original = caseFile([target("target_a")]);
    const first = deferred<Response>();
    let putCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          putCount += 1;
          return first.promise;
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(original));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const { unmount } = renderHarness();
    await screen.findByText("video: fixture.mp4");
    fireEvent.click(screen.getByText("Edit two"));
    await waitFor(() => expect(putCount).toBe(1));
    fireEvent.click(screen.getByText("Edit three"));

    unmount();
    first.resolve(
      response({
        ...original,
        revision: "accepted-two",
        targets: [target("target_a", [sample("target_a-sample", 2)])],
      }),
    );
    await new Promise((resolve) => window.setTimeout(resolve, 10));

    expect(putCount).toBe(1);
  });

  it("does not resume a settled save continuation after unmount", async () => {
    const original = caseFile([target("target_a")]);
    const first = deferred<Response>();
    const later = deferred<Response>();
    let putCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/eval-directory") return Promise.resolve(response(evalDirectory()));
        if (init?.method === "PUT") {
          putCount += 1;
          return putCount === 1 ? first.promise : later.promise;
        }
        if (url.includes("/api/case-files/")) return Promise.resolve(response(original));
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const { unmount } = renderHarness();
    await screen.findByText("video: fixture.mp4");
    fireEvent.click(screen.getByText("Edit two"));
    await waitFor(() => expect(putCount).toBe(1));
    fireEvent.click(screen.getByText("Edit three"));

    const realSetTimeout = window.setTimeout.bind(window);
    vi.useFakeTimers();
    first.resolve(
      response({
        ...original,
        revision: "accepted-two",
        targets: [target("target_a", [sample("target_a-sample", 2)])],
      }),
    );
    await new Promise<void>((resolve) => realSetTimeout(resolve, 0));
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    unmount();
    await vi.runAllTimersAsync();

    expect(putCount).toBe(1);
  });
});
