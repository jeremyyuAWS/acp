import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Proves Discover wires the durable job's attempts/max_attempts (GET /jobs/{id}, via
// getQueueJob) into QueueJobDetails.jsx's "Processing details" row, and — the actual bug this
// fixes — that the row stays available for the WHOLE busy window, not just the pre-listing
// queued phase. discoverJobInfo's polling effect used to stop (and null itself out) the instant
// progress.phase left 'queued', so QueueJobDetails could never show attempts/max_attempts once
// discovery actually started — exactly when someone would go looking for them.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getQueueJob = vi.fn()
const getJobs = vi.fn()
vi.mock('./api.js', () => ({
  checkReadiness: vi.fn(() => Promise.resolve(null)),
  getScanInventory: vi.fn(() => Promise.resolve(null)),
  listScanDecisions: vi.fn(() => Promise.resolve([])),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
  getQueueJob: (...a) => getQueueJob(...a),
  getJobs: (...a) => getJobs(...a),
  setWorkers: vi.fn(),
}))

const { default: Discover } = await import('./Discover.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: true, onScan: () => {}, ...props }))
  })
  return container
}
const rerender = async (props) => {
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: true, onScan: () => {}, ...props }))
  })
}
const settle = async (n = 5) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
afterEach(() => { unmountAll(); getQueueJob.mockReset(); getJobs.mockReset() })

const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))

describe('QueueJobDetails wiring on Discover', () => {
  it('shows the expandable row with attempts/max_attempts once getQueueJob resolves', async () => {
    getJobs.mockResolvedValue({ workers: 2, worker_tier_alive: true })
    getQueueJob.mockResolvedValue({ id: 'job-abc123', status: 'running', attempts: 1, max_attempts: 5 })
    const c = await mount({ jobId: 'job-abc123', progress: { phase: 'queued' } })
    await settle()
    const toggle = byText(c, 'button', /Processing details/)
    expect(toggle).toBeTruthy()
    await act(async () => { toggle.click() })
    expect(c.textContent).toMatch(/Attempt 2 of 5/)
    expect(c.textContent).toMatch(/Job ID …abc123/)
  })

  it('keeps showing attempts once the phase moves past queued into discovering — the actual bug', async () => {
    getJobs.mockResolvedValue({ workers: 2, worker_tier_alive: true })
    getQueueJob.mockResolvedValue({ id: 'job-abc123', status: 'running', attempts: 0, max_attempts: 5 })
    const c = await mount({ jobId: 'job-abc123', progress: { phase: 'queued' } })
    await settle()
    expect(byText(c, 'button', /Processing details/)).toBeTruthy()

    // The scan progresses past the pre-listing window — discoverJobInfo used to be wiped to null
    // here, and the row along with it.
    await rerender({ jobId: 'job-abc123', progress: { phase: 'discovering', files_found: 40 } })
    await settle()
    expect(byText(c, 'button', /Processing details/)).toBeTruthy()
  })

  it('does not render at all once the scan is no longer busy', async () => {
    getJobs.mockResolvedValue({ workers: 2, worker_tier_alive: true })
    getQueueJob.mockResolvedValue({ id: 'job-abc123', status: 'done', attempts: 1, max_attempts: 5 })
    const c = await mount({ jobId: 'job-abc123', progress: { phase: 'queued' }, busy: false })
    await settle()
    expect(byText(c, 'button', /Processing details/)).toBeFalsy()
  })

  it('does not render when there is no jobId at all (e.g. the default, non-queued scan path)', async () => {
    getJobs.mockResolvedValue({ workers: 2, worker_tier_alive: true })
    const c = await mount({ jobId: null, progress: { phase: 'discovering', files_found: 5 } })
    await settle()
    expect(getQueueJob).not.toHaveBeenCalled()
    expect(byText(c, 'button', /Processing details/)).toBeFalsy()
  })
})
