import { describe, expect, it } from "vitest";
import { shouldHandleShortcut } from "./shortcuts.ts";

describe("keyboard shortcut filtering", () => {
  it("allows an unmodified shortcut from the document body", () => {
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: "a", bubbles: true }))).toBe(
      true,
    );
  });

  it("ignores interactive targets, modifiers, repeats, and handled events", () => {
    const input = document.createElement("input");
    const interactive = new KeyboardEvent("keydown", { key: "a", bubbles: true });
    Object.defineProperty(interactive, "target", { value: input });
    expect(shouldHandleShortcut(interactive)).toBe(false);
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: "a", ctrlKey: true }))).toBe(
      false,
    );
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: "a", repeat: true }))).toBe(
      false,
    );
    const handled = new KeyboardEvent("keydown", {
      key: "a",
      cancelable: true,
    });
    handled.preventDefault();
    expect(shouldHandleShortcut(handled)).toBe(false);
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: " ", shiftKey: true }))).toBe(
      false,
    );
    expect(
      shouldHandleShortcut(new KeyboardEvent("keydown", { key: "ArrowLeft", shiftKey: true })),
    ).toBe(true);
  });
});
