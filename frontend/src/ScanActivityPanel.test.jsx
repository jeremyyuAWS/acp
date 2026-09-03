import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import axe from 'axe-core'
import { createTestRoot, unmountAll } from './testRoots.js'

const getSessionTraceData = vi.fn(() => Promise.resolve({ status: 'ok', session: {
  total: 3, truncated: false, rollup: { documents: 3, assessed: 2 }, files: [
    { trace_id: 's1::doc-a.docx', document: 'doc-a.docx', format: 'docx', result: { score: 82, remediation: { remediated: true } } },
    { trace_id: 's1::doc-b.pdf', document: 'doc-b.pdf', format: 'pdf', result: { score: 70 } },
    { trace_id: 's1::doc-c.pptx', document: 'doc-c.pptx', format: 'pptx', result: null },
  ],
}}))
vi.mock('./api.js', () => ({
  getSessionTraceData,
  getFileTraceData: vi.fn(() => Promise.resolve({ status: 'pending' })),
  openTraceUrl: vi.fn(() => null),
  getDocumentTraceHistory: vi.fn(() => Promise.resolve({ status: 'pending' })),
}))
const ScanActivityPanel = (await import('./ScanActivityPanel.jsx')).default
afterEach(() => { unmountAll(); vi.clearAllMocks() })
async function render() {
  const { container, root } = createTestRoot()
  await act(async () => root.render(createElement(ScanActivityPanel, { run: { id: 's1', completed_at: '2026-09-03T10:00:00Z', source: 'drive' }, scanList: [{ id: 's1', completed_at: '2026-09-03T10:00:00Z' }, { id: 's0', completed_at: '2026-09-02T10:00:00Z' }] })))
  for (let i = 0; i < 3; i++) await act(async () => new Promise((r) => setTimeout(r, 0)))
  return container
}

describe('scan activity', () => {
  it('shows the scan-level funnel and file-level stage status', async () => {
    const c = await render()
    expect(getSessionTraceData).toHaveBeenCalledWith('s1')
    expect(c.textContent).toContain('Discovered3')
    expect(c.textContent).toContain('Assessed2')
    expect(c.textContent).toContain('Remediated1')
    expect(c.textContent).toContain('doc-a.docx')
    expect(c.textContent).toContain('View timeline')
  })

  it('passes automated accessibility checks', async () => {
    const c = await render()
    const result = await axe.run(c, { rules: { region: { enabled: false } } })
    expect(result.violations).toEqual([])
  })
})
