import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DelayedSeekingStatus } from "./VideoPanel.tsx";

describe("DelayedSeekingStatus", () => {
  it("stays hidden for fast seeks and appears when a seek is still pending", () => {
    vi.useFakeTimers();
    render(<DelayedSeekingStatus />);

    expect(screen.queryByText("Seeking…")).toBeNull();
    act(() => vi.advanceTimersByTime(199));
    expect(screen.queryByText("Seeking…")).toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByText("Seeking…")).toBeTruthy();
  });
});
