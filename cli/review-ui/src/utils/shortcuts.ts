export function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  return Boolean(
    target.closest(
      'input, textarea, select, button, a, video, [contenteditable="true"], [role="button"], [role="link"]',
    ),
  )
}

export function shouldHandleShortcut(event: KeyboardEvent): boolean {
  return !(
    event.defaultPrevented ||
    event.isComposing ||
    event.repeat ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    (event.shiftKey &&
      event.key !== 'ArrowLeft' &&
      event.key !== 'ArrowRight') ||
    isInteractiveTarget(event.target)
  )
}
