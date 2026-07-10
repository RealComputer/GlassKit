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

  it('normalizes a whitespace-only optional field to null before autosave', async () => {
    const doc = caseDocument([target('target_a', [point('first', 1, 'true')])])
    let putBody: unknown = null
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/suite') return Promise.resolve(response(suite()))
        if (init?.method === 'PUT') {
          putBody = JSON.parse(String(init.body)) as unknown
          return Promise.resolve(response(doc))
        }
        if (url.includes('/api/cases/')) return Promise.resolve(response(doc))
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
    render(<App />)
    const field = await screen.findByLabelText(/Field/)
    fireEvent.change(field, { target: { value: '   ' } })

    await waitFor(() => expect(putBody).not.toBeNull())
    expect(putBody).toMatchObject({
      targets: { target_a: { points: [{ field: null }] } },
    })
  })
})
