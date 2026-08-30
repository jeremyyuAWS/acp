import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Live 2026-08-30 UX review: the scan button said "scanning…" the entire time a Discovery job
// was queued — before any worker had claimed it — the same "active work" implication the queued
// card's "Loading your inventory…" was found making at once (see discoverPendingScanLoad.test.jsx).
// Once a worker actually claims the job, "scanning…" becomes true and stays.

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

describe('the "Re-scan all sources" button label distinguishes queued from actually processing', () => {
  it('says "Re-scan all sources" when idle', async () => {
    const c = await mount({ scope: null, run: { id: 's1', status: 'discovered' }, busy: false })
    expect(rescanBtn(c)?.textContent).toBe('Re-scan all sources')
  })

  it('says "Queued" while busy and queued, before a worker has claimed the job', async () => {
    getQueueJob.mockResolvedValue(null)
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'queued' },
    })
    await settle()
    expect(rescanBtn(c)?.textContent).toBe('Queued')
  })

  it('says "scanning…" once the job is claimed, even while phase is still queued', async () => {
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', locked_at: new Date().toISOString() })
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'queued' },
    })
    await settle()
    expect(rescanBtn(c)?.textContent).toBe('scanning…')
  })

  it('says "scanning…" once past the queued phase (actively discovering)', async () => {
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true,
      progress: { phase: 'discovering' },
    })
    await settle()
    expect(rescanBtn(c)?.textContent).toBe('scanning…')
  })

  it('the button stays disabled in every busy state', async () => {
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true,
      progress: { phase: 'queued' },
    })
    await settle()
    expect(rescanBtn(c)?.disabled).toBe(true)
  })
})
