import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// The cross-scan "this document over time" panel: a score trajectory + a row per scan (newest
// first), each drilling into that scan's trace via the onOpenScan callback (no TracePanel import,
// so no cycle). Pins the trend, the rows, the single-scan case, the honest states, and that a row
// click reports the scan id — and that no operator identity is shown.

let mockHistory
vi.mock('./api.js', () => ({ getDocumentHistory: () => Promise.resolve(mockHistory) }))

const { default: DocumentHistoryPanel } = await import('./DocumentHistoryPanel.jsx')

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(DocumentHistoryPanel, { scanId: 'scan-cur', docLabel: 'doc-aaa.docx', onClose: () => {}, ...props })) })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return container
}

const OK = { status: 'ok', history: {
  document: 'doc-aaa.docx', format: 'docx', total: 3,
  scans: [
    { scan_id: 'scan-cur', trace_id: 'scan-cur::doc-aaa.docx', timestamp: '2026-08-19T17:00:00Z', result: { score: 82, conformant: false, level: 'AA', failing_criteria: { '1.4.3': 1 } } },
    { scan_id: 'h2', trace_id: 'h2::doc-aaa.docx', timestamp: '2026-06-10T09:00:00Z', result: { score: 71, conformant: false, level: 'AA', failing_criteria: { '1.1.1': 2 } } },
    { scan_id: 'h1', trace_id: 'h1::doc-aaa.docx', timestamp: '2026-06-03T09:00:00Z', result: { score: 60, conformant: false, level: 'AA', failing_criteria: { '1.1.1': 3 } } },
  ] } }

beforeEach(() => { mockHistory = OK })
afterEach(unmountAll)

describe('DocumentHistoryPanel', () => {
  it('shows a trajectory and one row per scan, newest first', async () => {
    const c = await mount()
    const t = c.textContent
    expect(t).toContain('3 scans')
    expect(t).toContain('since first scan')     // the trend delta line
    // 60 → 82 is a +22 improvement
    expect(t).toContain('+22')
    // sparkline: one bar per scored scan
    expect(c.querySelectorAll('.dh-bar').length).toBe(3)
    // the current scan is marked, no operator identity anywhere
    expect(t).toContain('this scan')
    expect(t).not.toContain('@')
  })

  it('drill-in reports the clicked scan id via onOpenScan', async () => {
    const opened = []
    const c = await mount({ onOpenScan: (sid) => opened.push(sid) })
    const rows = [...c.querySelectorAll('button.sp-row')]
    expect(rows.length).toBe(3)
    await act(async () => { rows[1].click() })      // the middle (h2) scan
    expect(opened).toEqual(['h2'])
  })

  it('a single-scan document shows no trajectory yet', async () => {
    mockHistory = { status: 'ok', history: { document: 'doc-aaa.docx', format: 'docx', total: 1,
      scans: [OK.history.scans[0]] } }
    const c = await mount()
    expect(c.textContent).toContain('Seen in one scan so far')
    expect(c.querySelector('.dh-spark')).toBeNull()
  })

  it('shows honest pending and not-configured states', async () => {
    mockHistory = { status: 'pending' }
    let c = await mount()
    expect(c.textContent.toLowerCase()).toContain('hasn’t finished recording')
    mockHistory = { status: 'not_configured' }
    c = await mount()
    expect(c.textContent.toLowerCase()).toContain('configured')
  })
})
