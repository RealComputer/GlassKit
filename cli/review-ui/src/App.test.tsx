import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.tsx'
import { document as caseDocument, point, suite, target } from './test/fixtures.ts'

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('review application navigation and drafts', () => {
  it('keeps an invalid partial expectation selected during blur and point navigation', async () => {
    const doc = caseDocument([
      target('numeric_target', [point('first', 1, '1'), point('second', 2, '2')]),
    ])
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (url.includes('/api/cases/')) return Promise.resolve(response(doc))
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    render(<App />)

    const expected = await screen.findByLabelText('Expected value')
    await waitFor(() => expect(expected).toHaveProperty('value', '1'))
    fireEvent.change(expected, { target: { value: '-' } })
    fireEvent.blur(expected)
    const secondRow = screen
      .getAllByText('2.000s')
      .find((element) => element.tagName === 'TD')
      ?.closest('tr')
    expect(secondRow).not.toBeNull()
    fireEvent.click(secondRow!)

    expect(screen.getByLabelText('Timestamp')).toHaveProperty('value', '1')
    expect(screen.getByText('Fix errors')).toBeTruthy()
    expect(screen.getByText('Enter a valid JSON number.')).toBeTruthy()
  })

  it('treats a whitespace-only optional field as an unchanged null value', async () => {
    const doc = caseDocument([target('target_a', [point('first', 1, 'true')])])
    let putCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (init?.method === 'PUT') {
          putCount += 1
          return Promise.resolve(response(doc))
        }
        if (url.includes('/api/cases/')) return Promise.resolve(response(doc))
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    render(<App />)
    const field = await screen.findByLabelText(/Field/)
    fireEvent.change(field, { target: { value: '   ' } })
    fireEvent.blur(field)
    await new Promise((resolve) => window.setTimeout(resolve, 450))

    expect(putCount).toBe(0)
  })

  it('commits human-entered transport time only on Enter', async () => {
    const doc = caseDocument([target('target_a', [point('first', 1, 'true')])])
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (url.includes('/api/cases/')) return Promise.resolve(response(doc))
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    render(<App />)
    const time = await screen.findByLabelText('Time')
    await waitFor(() => expect(time).toHaveProperty('value', '1.000'))
    fireEvent.focus(time)
    fireEvent.change(time, { target: { value: '1.234' } })
    expect(time).toHaveProperty('value', '1.234')
    fireEvent.keyDown(time, { key: 'Enter' })
    expect(time).toHaveProperty('value', '1.234')
  })

  it('suppresses shortcuts inside overlays, traps focus, and restores the opener', async () => {
    const doc = caseDocument([target('target_a', [point('first', 1, 'true')])])
    let putCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (init?.method === 'PUT') {
          putCount += 1
          return Promise.resolve(response(doc))
        }
        if (url.includes('/api/cases/')) return Promise.resolve(response(doc))
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    render(<App />)
    const time = await screen.findByLabelText('Time')
    fireEvent.focus(time)
    fireEvent.change(time, { target: { value: '1.234' } })
    fireEvent.keyDown(time, { key: 'Enter' })

    const opener = screen.getByLabelText('Show keyboard shortcuts')
    opener.focus()
    fireEvent.click(opener)
    const close = await screen.findByLabelText('Close keyboard shortcuts')
    await waitFor(() => expect(document.activeElement).toBe(close))
    fireEvent.keyDown(window, { key: 'a' })
    fireEvent.keyDown(window, { key: 'Tab' })
    expect(document.activeElement).toBe(close)
    fireEvent.click(close)
    await waitFor(() => expect(document.activeElement).toBe(opener))

    const sourceOpener = screen.getByText('Case YAML')
    sourceOpener.focus()
    fireEvent.click(sourceOpener)
    await screen.findByLabelText('Close source drawer')
    fireEvent.keyDown(window, { key: 'a' })
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(document.activeElement).toBe(sourceOpener))
    await new Promise((resolve) => window.setTimeout(resolve, 450))

    expect(putCount).toBe(0)
  })

  it('does not dirty unchanged inspector fields on blur', async () => {
    const unchangedPoint = {
      ...point('first', 1, '1'),
      field: 'confidence',
      comment: 'No change',
      compare: { mode: 'numeric' as const, tolerance: 0.1 },
    }
    const doc = caseDocument([target('numeric_target', [unchangedPoint])])
    let putCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (init?.method === 'PUT') {
          putCount += 1
          return Promise.resolve(response(doc))
        }
        if (url.includes('/api/cases/')) return Promise.resolve(response(doc))
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    render(<App />)
    const controls = await Promise.all([
      screen.findByLabelText('Timestamp'),
      screen.findByLabelText('Expected value'),
      screen.findByLabelText(/Field/),
      screen.findByLabelText('Tolerance'),
      screen.findByLabelText('Comment optional'),
    ])
    await waitFor(() => expect(controls[1]).toHaveProperty('value', '1'))
    for (const control of controls) {
      fireEvent.focus(control)
      fireEvent.blur(control)
    }
    await new Promise((resolve) => window.setTimeout(resolve, 450))

    expect(putCount).toBe(0)
  })

  it('keeps an invalid expectation draft visible across an older PUT response', async () => {
    const doc = caseDocument([target('numeric_target', [point('first', 1, '1')])])
    let resolvePut!: (response: Response) => void
    const put = new Promise<Response>((resolve) => {
      resolvePut = resolve
    })
    let putStarted = false
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (init?.method === 'PUT') {
          putStarted = true
          return put
        }
        if (url.includes('/api/cases/')) return Promise.resolve(response(doc))
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    render(<App />)
    const comment = await screen.findByLabelText('Comment optional')
    fireEvent.change(comment, { target: { value: 'Save this first' } })
    fireEvent.blur(comment)
    await waitFor(() => expect(putStarted).toBe(true))
    const expected = screen.getByLabelText('Expected value')
    fireEvent.change(expected, { target: { value: '-' } })
    const accepted = {
      ...doc,
      revision: 'accepted-comment',
      targets: [
        target('numeric_target', [
          { ...point('first', 1, '1'), comment: 'Save this first' },
        ]),
      ],
    }
    resolvePut(response(accepted))
    await waitFor(() => expect(screen.getByText('Fix errors')).toBeTruthy())

    expect(expected).toHaveProperty('value', '-')
    expect(screen.getByText('Enter a valid JSON number.')).toBeTruthy()
  })

  it('offers an explicit discard path for an invalid draft', async () => {
    const doc = caseDocument([target('numeric_target', [point('first', 1, '1')])])
    let gets = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (url.includes('/api/cases/')) {
          gets += 1
          return Promise.resolve(response({ ...doc }))
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    render(<App />)
    const expected = await screen.findByLabelText('Expected value')
    await waitFor(() => expect(expected).toHaveProperty('value', '1'))
    fireEvent.change(expected, { target: { value: '-' } })
    fireEvent.click(await screen.findByText('Discard drafts'))
    await waitFor(() => expect(expected).toHaveProperty('value', '1'))

    expect(gets).toBe(2)
    expect(screen.queryByText('Fix errors')).toBeNull()
  })
})
