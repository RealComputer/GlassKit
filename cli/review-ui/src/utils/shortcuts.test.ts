import { describe, expect, it } from "vitest";
import { shouldHandleShortcut } from "./shortcuts.ts";

function keyboardEventFrom(target: Element, key: string): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { key, bubbles: true });
  Object.defineProperty(event, "target", { value: target });
  return event;
}

describe("keyboard shortcut filtering", () => {
  it("allows an unmodified shortcut from the document body", () => {
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: "a", bubbles: true }))).toBe(
      true,
    );
  });

  it("keeps shortcuts out of controls that own arbitrary keyboard input", () => {
    const input = document.createElement("input");
    expect(shouldHandleShortcut(keyboardEventFrom(input, "a"))).toBe(false);
    expect(shouldHandleShortcut(keyboardEventFrom(input, "]"))).toBe(false);
  });

  it("allows navigation from buttons while preserving their Space activation", () => {
    const button = document.createElement("button");
    expect(shouldHandleShortcut(keyboardEventFrom(button, "]"))).toBe(true);
    expect(shouldHandleShortcut(keyboardEventFrom(button, "ArrowRight"))).toBe(true);
    expect(shouldHandleShortcut(keyboardEventFrom(button, " "))).toBe(false);
  });

  it("allows repeats for continuous navigation shortcuts only", () => {
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: "]", repeat: true }))).toBe(
      true,
    );
    expect(
      shouldHandleShortcut(new KeyboardEvent("keydown", { key: "ArrowRight", repeat: true })),
    ).toBe(true);
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: "a", repeat: true }))).toBe(
      false,
    );
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: " ", repeat: true }))).toBe(
      false,
    );
  });

  it("ignores modifiers and handled events", () => {
    expect(shouldHandleShortcut(new KeyboardEvent("keydown", { key: "a", ctrlKey: true }))).toBe(
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
