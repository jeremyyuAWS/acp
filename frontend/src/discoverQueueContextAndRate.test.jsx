import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// PRD "Live Discover Journey" — the richer queued card (compatible jobs ahead / worker pool /
// submitted time) and the live-activity facts (recent discovery rate / folders found / inventory
// updated) added on top of the "Worker assigned" work in discoverWorkerAssigned.test.jsx. Proves
// Discover actually wires GET /jobs into the queued-card facts, and that the client-side rate
// computation reacts to real progress.files_found deltas across ticks. The pure derivation is
// covered on its own in discoverProcessingState.test.js; this is the DOM leg.

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
  setWorkers: vi.fn(() => Promise.resolve({ workers: 0 })),
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
const rerender = async (props) => {
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
// Discover also mounts an UNCONDITIONAL worker-availability poll (WorkerAvailability, #925) that
// calls this same getJobs() on every render regardless of busy/phase — give it a default so a
// test that isn't exercising that strip doesn't hit a bare, unresolved vi.fn().
//
// getQueueJob() gets the same treatment for the same reason, since discoverJobInfo's own poll
// (Discover.jsx) now runs for the WHOLE busy window rather than stopping once progress.phase
// leaves 'queued' — QueueJobDetails.jsx's "Processing details" row needs attempts/max_attempts
// past that point, which is exactly what used to get wiped. A test that isn't exercising THAT
// row still needs a resolved value here or it hits the same bare, unresolved vi.fn().
beforeEach(() => {
  getJobs.mockResolvedValue({ workers: 0, worker_tier_alive: false, jobs: [] })
  getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', attempts: 0, max_attempts: 5 })
})
afterEach(() => { unmountAll(); getQueueJob.mockReset(); getJobs.mockReset() })

// ProcessingStatusPanel renders each fact as a [label-div, value-div] pair — find the value next
// to a given label rather than grepping flattened textContent, which concatenates adjacent
// elements with no separator (e.g. "ahead" immediately followed by "2").
const factValue = (c, label) => {
  const labelEl = [...c.querySelectorAll('div')].find((d) => d.textContent === label)
  return labelEl?.nextElementSibling?.textContent ?? null
}

describe('the richer queued card', () => {
  it('shows compatible-jobs-ahead, worker-pool and submitted facts from GET /jobs', async () => {
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued', locked_at: null })
    getJobs.mockResolvedValue({
      workers: 4, worker_tier_alive: true,
      jobs: [
        { id: 'j1', type: 'scan_discover', status: 'queued' },
        { id: 'j2', type: 'scan_discover', status: 'queued' },
        { id: 'j3', type: 'scan_batch', status: 'queued' },
        { id: 'j4', type: 'remediate_file', status: 'queued' },   // not a discovery-lane type
      ],
    })
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'queued', started_at: new Date(Date.now() - 130000).toISOString() },
    })
    await settle()
    expect(getJobs).toHaveBeenCalledWith('queued')
    // j2 + j3 (compatible, queued, not self); j1 excluded as self, j4 excluded as the wrong lane.
    expect(factValue(c, 'Compatible jobs ahead')).toBe('2')
    expect(factValue(c, 'Worker pool')).toBe('4 online')
    expect(factValue(c, 'Submitted')).toBe('2m ago')
  })

  it('shows the worker pool as offline when the tier has no heartbeat', async () => {
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued', locked_at: null })
    getJobs.mockResolvedValue({ workers: 0, worker_tier_alive: false, jobs: [] })
    const c = await mount({
      scope: null, run: { id: 's2', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'queued' },
    })
    await settle()
    expect(factValue(c, 'Worker pool')).toBe('offline')
  })

  it('stops asking for queue context once real listing progress has started', async () => {
    // getJobs() itself is still called — WorkerAvailability (#925) polls it unconditionally,
    // the whole time this tab is mounted, for an unrelated reason (ambient worker-pool
    // visibility). This queue-context effect's own call — status='queued' — is what should stop.
    await mount({
      scope: null, run: { id: 's3', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'discovering', elapsed: 5, files_found: 10 },
    })
    await settle()
    expect(getJobs).not.toHaveBeenCalledWith('queued')
  })
})

describe('the live discovery-rate facts', () => {
  it('shows files-found and folders-found immediately, but withholds the rate until samples span an interval', async () => {
    const c = await mount({
      scope: null, run: { id: 's4', status: 'running' }, busy: true, jobId: null,
      progress: { phase: 'discovering', elapsed: 1, files_found: 100, folders_found: 3 },
    })
    await settle()
    expect(factValue(c, 'Files found')).toBe('100')
    expect(factValue(c, 'Folders found')).toBe('3')
    expect(factValue(c, 'Recent discovery rate')).toBeNull()
  })

  it('derives a recent discovery rate once files_found grows across two ticks a second apart', async () => {
    const c = await mount({
      scope: null, run: { id: 's5', status: 'running' }, busy: true, jobId: null,
      progress: { phase: 'discovering', elapsed: 1, files_found: 100 },
    })
    await settle()
    const realNow = Date.now
    Date.now = () => realNow() + 2000
    await rerender({
      scope: null, run: { id: 's5', status: 'running' }, busy: true, jobId: null,
      progress: { phase: 'discovering', elapsed: 3, files_found: 146 },
    })
    await settle()
    Date.now = realNow
    expect(factValue(c, 'Recent discovery rate')).toBe('23 files/sec')
  })

  it('resets the rate and inventory-changed tracking once the run stops being busy', async () => {
    const c = await mount({
      scope: null, run: { id: 's6', status: 'running' }, busy: true, jobId: null,
      progress: { phase: 'discovering', elapsed: 1, files_found: 100 },
    })
    await settle()
    await rerender({ scope: null, run: { id: 's6', status: 'discovered' }, busy: false })
    await settle()
    expect(factValue(c, 'Recent discovery rate')).toBeNull()
  })
})
