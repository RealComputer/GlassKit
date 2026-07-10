import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CaseDocument } from '../api/types.ts'
import { document as caseDocument, point, suite, target } from '../test/fixtures.ts'
import { AppProvider, useApp } from './AppContext.tsx'

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function Harness() {
  const {
    state,
    updatePoint,
    reloadFromDisk,
    flushCurrentCase,
    selectCase,
  } = useApp()
  const [flushed, setFlushed] = useState('idle')
  const workspace = state.selectedCaseId
    ? state.documents[state.selectedCaseId]
    : null
  const currentPoint = workspace?.document.targets[0]?.points[0]
  return (
    <div>
      <output data-testid="source">{workspace?.document.source_yaml}</output>
      <output data-testid="time">{currentPoint?.timestamp_s}</output>
      <output data-testid="phase">{workspace?.savePhase}</output>
      <output data-testid="flushed">{flushed}</output>
      <output data-testid="selected-case">{state.selectedCaseId}</output>
      <output data-testid="selected-target">{state.selectedTargetId}</output>
      <output data-testid="video-time">{state.video.currentTime}</output>
      <button
        type="button"
        onClick={() =>
          currentPoint &&
          updatePoint('target_a', currentPoint.id, { timestamp_s: 2 }, true)
        }
      >
        Edit two
      </button>
      <button
        type="button"
        onClick={() =>
          currentPoint &&
          updatePoint('target_a', currentPoint.id, { timestamp_s: 3 }, true)
        }
      >
        Edit three
      </button>
      <button type="button" onClick={() => void reloadFromDisk()}>
        Reload
      </button>
      <button
        type="button"
        onClick={() =>
          void flushCurrentCase().then((ok) => setFlushed(String(ok)))
        }
      >
        Flush
      </button>
      <button type="button" onClick={() => void selectCase('case-002.yml')}>
        Switch case
      </button>
    </div>
  )
}

function renderHarness() {
  render(
    <AppProvider>
      <Harness />
    </AppProvider>,
  )
}

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('case save queue', () => {
  it('keeps a later-selected case active when the earlier GET resolves last', async () => {
    const first = deferred<Response>()
    const second = deferred<Response>()
    const firstDocument = {
      ...caseDocument([target('first_target', [point('first-point', 2)])]),
      id: 'case-001.yaml',
      name: 'case-001',
    }
    const secondDocument = {
      ...caseDocument([target('second_target', [point('second-point', 7)])]),
      id: 'case-002.yml',
      name: 'case-002',
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (url.includes('case-001.yaml')) return first.promise
        if (url.includes('case-002.yml')) return second.promise
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    renderHarness()
    await screen.findByText('case-001.yaml')
    fireEvent.click(screen.getByText('Switch case'))
    second.resolve(response(secondDocument))
    await screen.findByText('second_target')
    first.resolve(response(firstDocument))
    await new Promise((resolve) => window.setTimeout(resolve, 10))

    expect(screen.getByTestId('selected-case').textContent).toBe('case-002.yml')
    expect(screen.getByTestId('selected-target').textContent).toBe('second_target')
    expect(screen.getByTestId('video-time').textContent).toBe('7')
  })

  it('invalidates a late PUT response after reload from disk', async () => {
    const original = { ...caseDocument([target('target_a')]), source_yaml: 'original' }
    const reloaded = {
      ...caseDocument([target('target_a', [point('target_a-point', 1, 'true')])]),
      source_yaml: 'reloaded',
      revision: 'reload-revision',
    }
    const late = {
      ...caseDocument([target('target_a', [point('target_a-point', 2)])]),
      source_yaml: 'late response',
      revision: 'late-revision',
    }
    const put = deferred<Response>()
    let caseGets = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (init?.method === 'PUT') return put.promise
        if (url.includes('/api/cases/')) {
          caseGets += 1
          return Promise.resolve(response(caseGets === 1 ? original : reloaded))
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    renderHarness()
    await screen.findByText('original')
    fireEvent.click(screen.getByText('Edit two'))
    await waitFor(() => expect(screen.getByTestId('phase').textContent).toBe('saving'))
    fireEvent.click(screen.getByText('Reload'))
    expect(caseGets).toBe(1)
    put.resolve(response(late))
    await screen.findByText('reloaded')

    expect(screen.getByTestId('source').textContent).toBe('reloaded')
    expect(screen.getByTestId('time').textContent).toBe('1')
  })

  it('flushes a newer version after an older in-flight save before resolving', async () => {
    const original = caseDocument([target('target_a')])
    const first = deferred<Response>()
    const second = deferred<Response>()
    const putBodies: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (init?.method === 'PUT') {
          putBodies.push(JSON.parse(String(init.body)) as unknown)
          return putBodies.length === 1 ? first.promise : second.promise
        }
        if (url.includes('/api/cases/')) return Promise.resolve(response(original))
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    renderHarness()
    await screen.findByText('video: fixture.mp4')
    fireEvent.click(screen.getByText('Edit two'))
    await waitFor(() => expect(putBodies).toHaveLength(1))
    fireEvent.click(screen.getByText('Edit three'))
    fireEvent.click(screen.getByText('Flush'))

    const acceptedTwo: CaseDocument = {
      ...original,
      targets: [target('target_a', [point('target_a-point', 2)])],
      revision: 'accepted-two',
    }
    first.resolve(response(acceptedTwo))
    await waitFor(() => expect(putBodies).toHaveLength(2))
    expect(putBodies[1]).toMatchObject({
      targets: { target_a: { points: [{ timestamp_s: 3 }] } },
    })
    const acceptedThree: CaseDocument = {
      ...original,
      targets: [target('target_a', [point('target_a-point', 3)])],
      revision: 'accepted-three',
    }
    second.resolve(response(acceptedThree))

    await waitFor(() => expect(screen.getByTestId('flushed').textContent).toBe('true'))
    expect(screen.getByTestId('time').textContent).toBe('3')
    expect(screen.getByTestId('phase').textContent).toBe('saved')
  })
})
