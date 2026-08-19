import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// The IN-APP trace panel renders a file's Langfuse trace inside AccessOps, so nobody has to log
// into Langfuse (whose own page hangs for logged-out users on our self-hosted v3). These pin the
// three states the backend can return, and that the panel shows the assessment result + timeline
// on the happy path — never the raw trace name (which carries an operator email; the backend
// strips it, and the panel is given no field to print it from).

let mockResult
vi.mock('./api.js', () => ({ getFileTraceData: (...a) => { mockCalls.push(a); return Promise.resolve(mockResult) } }))
let mockCalls = []

const { default: TracePanel } = await import('./TracePanel.jsx')

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(TracePanel, { scanId: 's1', file: 'doc-3f9a2c.docx', onClose: () => {}, ...props })) })
  // flush the fetch promise + its setState
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return container
}

beforeEach(() => { mockCalls = [] })
afterEach(unmountAll)

describe('TracePanel', () => {
  it('shows the score, failing criteria, PII and timeline on the happy path', async () => {
    mockResult = { status: 'ok', trace: {
      id: 's1::doc-3f9a2c.docx', document: 'doc-3f9a2c.docx', format: 'docx',
      result: { score: 82, conformant: false, level: 'AA', failing_criteria: { '1.1.1': 1, '1.4.3': 3 },
        pii: { flagged: true, types: ['us_ssn'], findings: 2, critical: false },
        remediation: { remediated: true, written_back: false, published: false } },
      observations: [
        { type: 'SPAN', name: 'Discover', start: '2026-06-29T17:04:10Z', end: '2026-06-29T17:04:11Z' },
        { type: 'GENERATION', name: 'alt-text', start: '2026-06-29T17:04:14Z', end: '2026-06-29T17:04:16Z', model: 'llava:13b', input_tokens: 512, output_tokens: 48, cost: 0.0011 },
      ] } }
    const c = await mount()
    const text = c.textContent
    expect(text).toContain('82')
    expect(text).toContain('1.1.1')
    expect(text).toContain('1.4.3')
    expect(text).toContain('Discover')
    expect(text).toContain('alt-text')
    expect(text).toContain('llava:13b')
    // the panel is passed the redacted label as the title; no email anywhere
    expect(text).not.toContain('@')
    // it fetched for the right scan + file
    expect(mockCalls[0]).toEqual(['s1', 'doc-3f9a2c.docx'])
  })

  it('shows an honest "still recording" state with a Retry when the trace is pending', async () => {
    mockResult = { status: 'pending' }
    const c = await mount()
    expect(c.textContent.toLowerCase()).toContain('recording')
    const retry = [...c.querySelectorAll('button')].find((b) => /retry/i.test(b.textContent))
    expect(retry).toBeTruthy()
  })

  it('says nothing to show when tracing is not configured', async () => {
    mockResult = { status: 'not_configured' }
    const c = await mount()
    expect(c.textContent.toLowerCase()).toContain('configured')
  })

  it('never renders a PII value — only the type category', async () => {
    mockResult = { status: 'ok', trace: {
      document: 'doc-x.docx', format: 'docx',
      result: { score: 70, conformant: false, level: 'AA', failing_criteria: {},
        pii: { flagged: true, types: ['us_ssn'], findings: 3, critical: true }, remediation: null },
      observations: [] } }
    const c = await mount()
    expect(c.textContent).toContain('us_ssn')          // the category shows
    expect(c.textContent).not.toContain('123-45')      // no value ever would
  })
})
