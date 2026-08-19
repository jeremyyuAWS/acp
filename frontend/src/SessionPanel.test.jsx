import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// The in-app SESSION panel lists a whole scan's document traces with a scan-level rollup, so the
// aggregate that hung Langfuse's own UI renders inside AccessOps. These pin the rollup + rows on
// the happy path, the honest empty/pending/not-configured states, and that a row drills into the
// file TracePanel (which fetches the per-file trace).

let mockSession, mockFile
vi.mock('./api.js', () => ({
  getSessionTraceData: () => Promise.resolve(mockSession),
  getFileTraceData: (...a) => { fileCalls.push(a); return Promise.resolve(mockFile) },
}))
let fileCalls = []

const { default: SessionPanel } = await import('./SessionPanel.jsx')

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(SessionPanel, { scanId: 's1', onClose: () => {}, ...props })) })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return { container, root }
}

beforeEach(() => { fileCalls = []; mockFile = { status: 'pending' } })
afterEach(unmountAll)

const OK = { status: 'ok', session: {
  id: 's1', total: 3, truncated: false,
  rollup: { documents: 3, assessed: 2, conformant: 1, avg_score: 74.5, with_failures: 1, with_pii: 1 },
  files: [
    { trace_id: 's1::doc-aaa.docx', document: 'doc-aaa.docx', format: 'docx',
      result: { score: 67, conformant: false, level: 'AA', failing_criteria: { '1.1.1': 2 }, pii: { flagged: true, types: ['us_ssn'] } } },
    { trace_id: 's1::doc-bbb.pdf', document: 'doc-bbb.pdf', format: 'pdf',
      result: { score: 82, conformant: true, level: 'AA', failing_criteria: {} } },
    { trace_id: 's1::doc-ccc.xlsx', document: 'doc-ccc.xlsx', format: 'xlsx', result: null },
  ] } }

describe('SessionPanel', () => {
  it('shows the rollup and one row per document', async () => {
    mockSession = OK
    const { container } = await mount()
    const t = container.textContent
    expect(t).toContain('doc-aaa.docx')
    expect(t).toContain('doc-bbb.pdf')
    expect(t).toContain('doc-ccc.xlsx')
    expect(t).toContain('documents')       // rollup labels
    expect(t).toContain('conformant')
    expect(t).toContain('not assessed')    // ccc has no result
    expect(t).not.toContain('@')           // no operator email anywhere
  })

  it('opens the file TracePanel when a document row is clicked', async () => {
    mockSession = OK
    const { container } = await mount()
    const row = [...container.querySelectorAll('button.sp-row')][0]
    await act(async () => { row.click() })
    await act(async () => { await Promise.resolve() })
    // the drill-in fetched the file trace for the clicked document
    expect(fileCalls[0]).toEqual(['s1', 'doc-aaa.docx'])
  })

  it('notes truncation honestly when the list is capped', async () => {
    mockSession = { status: 'ok', session: { ...OK.session, total: 900, truncated: true } }
    const { container } = await mount()
    expect(container.textContent).toContain('of 900')
  })

  it('shows a pending state with Retry', async () => {
    mockSession = { status: 'pending' }
    const { container } = await mount()
    expect(container.textContent.toLowerCase()).toContain('recording')
    expect([...container.querySelectorAll('button')].some((b) => /retry/i.test(b.textContent))).toBe(true)
  })

  it('says nothing to show when tracing is not configured', async () => {
    mockSession = { status: 'not_configured' }
    const { container } = await mount()
    expect(container.textContent.toLowerCase()).toContain('configured')
  })
})
