import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, 'ResizeObserver', {
  configurable: true,
  value: ResizeObserverStub,
})

Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  value: vi.fn(),
})

if (!globalThis.CSS) Object.defineProperty(globalThis, 'CSS', { value: {} })
if (!globalThis.CSS.escape) {
  Object.defineProperty(globalThis.CSS, 'escape', {
    value: (value: string) => value.replace(/[^a-zA-Z0-9_-]/g, '\\$&'),
  })
}
