import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Live 2026-08-30 UX review: the scan button said "scanning…" the entire time a Discovery job
// was queued — before any worker had claimed it — the same "active work" implication the queued
// card's "Loading your inventory…" was found making at once (see discoverPendingScanLoad.test.jsx).
// Once a worker actually claims the job, "scanning…" becomes true and stays.
//
// THE BUTTON IS GONE. Discover's "Re-scan all sources" was removed on 2026-09-02 (PRD "ACP
// Discover and Overview Simplification") — a scan is started from Sources, and Discover reports
// what one found. The DISTINCTION the button label carried is not gone: the processing-state panel
// still says "Waiting for a worker" while a job sits unclaimed and "Worker assigned" the moment one
// claims it, which is the same claim in more words and in the place a reader is already looking.
// That is what this file pins now, together with the button's absence — because a scan control
// that reappears on Discover has to reappear with this distinction intact.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getQueueJob = vi.fn()
vi.mock('./api.js', () => ({
  checkReadiness: vi.fn(() => Promise.resolve(null)),
  getScanInventory: vi.fn(() => Promise.resolve(null)),
  listScanDecisions: vi.fn(() => Promise.resolve([])),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
  getQueueJob: (...a) => getQueueJob(...a),
  getJobs: vi.fn(() => Promise.resolve({ jobs: [] })),
  getQueueEstimate: vi.fn(() => Promise.resolve({ available: false })),
}))

const { default: Discover } = await import('./Discover.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const rescanBtn = (c) => [...c.querySelectorAll('button')].find((b) => /^(Re-scan all sources|Queued|scanning…)$/.test(b.textContent))
afterEach(() => { unmountAll(); getQueueJob.mockReset() })

const panelText = (c) => c.textContent

describe('Discover carries no scan button, and says so by carrying none', () => {
  it('renders no scan control when idle', async () => {
    const c = await mount({ scope: null, run: { id: 's1', status: 'discovered' }, busy: false })
    expect(rescanBtn(c)).toBeUndefined()
    // Discover DID render — otherwise the absence above is a mount failure, not a removal.
    expect(panelText(c).length).toBeGreaterThan(0)
  })

  it('renders no scan control while busy either', async () => {
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true,
      progress: { phase: 'discovering' },
    })
    await settle()
    expect(rescanBtn(c)).toBeUndefined()
  })
})

describe('the queued-vs-claimed distinction the button label used to carry', () => {
  it('says a job is WAITING, not scanning, before a worker has claimed it', async () => {
    getQueueJob.mockResolvedValue(null)
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'queued' },
    })
    await settle()
    expect(panelText(c)).toContain('Waiting for a worker')
    expect(panelText(c)).not.toContain('Worker assigned')
  })

  it('says a worker is ASSIGNED once the job is claimed, even while phase is still queued', async () => {
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', locked_at: new Date().toISOString() })
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'queued' },
    })
    await settle()
    expect(panelText(c)).toContain('Worker assigned')
    expect(panelText(c)).not.toContain('Waiting for a worker')
  })
})
