import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// PRD "Live Discover Journey", Phase 1 — proves Discover actually polls GET /jobs/{id} (via
// getQueueJob) for its own discover job and feeds the claim signal into ProcessingStatusPanel,
// the same way processingStatusPanelIntegration.test.jsx proves it for AssessRunner. The pure
// derivation (deriveDiscoverProcessingState's new 'assigned' branch) is covered on its own in
// discoverProcessingState.test.js; this is the DOM leg.

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
  // Stubbed so the richer-queued-card poll (mounted alongside the claim poll while
  // busy && phase === 'queued') doesn't throw — its own behavior is covered in
  // discoverQueueContextAndRate.test.jsx, out of scope for this file.
  getJobs: vi.fn(() => Promise.resolve({ jobs: [] })),
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
afterEach(() => { unmountAll(); getQueueJob.mockReset() })

describe('Worker-assignment signal on Discover', () => {
  it('shows "Worker assigned" once GET /jobs/{id} reports the job claimed, while still queued', async () => {
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', locked_at: new Date(Date.now() - 5000).toISOString() })
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'queued' },
    })
    await settle()
    expect(getQueueJob).toHaveBeenCalledWith('j1')
    expect(c.textContent).toMatch(/worker assigned/i)
    expect(c.textContent).toMatch(/claimed this job \d+s ago/i)
  })

  it('keeps showing "Waiting for a worker" while GET /jobs/{id} still reports queued', async () => {
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued', locked_at: null })
    const c = await mount({
      scope: null, run: { id: 's2', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'queued' },
    })
    await settle()
    expect(c.textContent).toMatch(/waiting for a worker/i)
    expect(c.textContent).not.toMatch(/worker assigned/i)
  })

  it('keeps polling GET /jobs/{id} once real listing progress has started — QueueJobDetails.jsx '
     + 'needs attempts/max_attempts for the whole busy window, not just the pre-listing wait', async () => {
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', locked_at: new Date().toISOString(),
                                    attempts: 0, max_attempts: 5 })
    const c = await mount({
      scope: null, run: { id: 's3', status: 'running' }, busy: true, jobId: 'j1',
      progress: { phase: 'discovering', elapsed: 5, files_found: 10 },
    })
    await settle()
    expect(getQueueJob).toHaveBeenCalledWith('j1')
    // The claim signal ITSELF simply isn't read here any more: deriveDiscoverProcessingState's
    // 'assigned' branch only ever fires inside its own `phase === 'queued'` check, so "Worker
    // assigned" correctly stops appearing even though the poll that would feed it keeps running.
    expect(c.textContent).not.toMatch(/worker assigned/i)
  })

  it('does not poll when there is no jobId to ask about', async () => {
    const c = await mount({
      scope: null, run: { id: 's4', status: 'running' }, busy: true, jobId: null,
      progress: { phase: 'queued' },
    })
    await settle()
    expect(getQueueJob).not.toHaveBeenCalled()
    expect(c.textContent).toMatch(/waiting for a worker/i)
  })
})
