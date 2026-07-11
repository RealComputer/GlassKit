function targetOwnsShortcut(event: KeyboardEvent): boolean {
  if (!(event.target instanceof Element)) return false;
  if (
    event.target.closest(
      'input, textarea, select, video, [contenteditable]:not([contenteditable="false"])',
    )
  ) {
    return true;
  }
  return Boolean(
    event.key === " " && event.target.closest('button, a, [role="button"], [role="link"]'),
  );
}

export function shouldHandleShortcut(event: KeyboardEvent): boolean {
  return !(
    event.defaultPrevented ||
    event.isComposing ||
    event.repeat ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    (event.shiftKey && event.key !== "ArrowLeft" && event.key !== "ArrowRight") ||
    targetOwnsShortcut(event)
  );
}
