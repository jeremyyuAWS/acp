/**
 * Discover's capacity-state notice — GET /readyz is checked on mount (and again after any
 * scan finishes) so a worker outage reads as a notice BEFORE the click, instead of a
 * silent stall discovered only after clicking "Re-scan all sources" (the 2026-08-26 incident:
 * a queued job sat unclaimed with zero signal until the run "finished" showing 0 documents).
 *
 * The notice maps capacity_state → copy + color:
 *   "starting"    → blue "Preparing Discovery capacity" (can still scan; job will queue)
 *   "unavailable" → red "Discovery is temporarily unavailable" (infrastructure never started)
 *   "degraded"    → amber "Discovery capacity is limited"
 *
 * Non-blocking by design — "Re-scan all sources" stays enabled for starting/degraded.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

const checkReadiness = vi.fn()
vi.mock('./api.js', () => ({
  checkReadiness: (...a) => checkReadiness(...a),
  getScanInventory: vi.fn(),
  listScanDecisions: vi.fn(),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
  // Stubbed so the worker-availability poll (mounted unconditionally), the richer-queued-card
  // poll, and the job-claim poll (all mounted whenever busy && phase is queued-or-unset) don't
  // throw — their own behavior is covered in discoverWorkerAvailability.test.jsx,
  // discoverQueueContextAndRate.test.jsx, and discoverWorkerAssigned.test.jsx respectively,
  // out of scope for this file.
  getJobs: vi.fn(() => Promise.resolve({ jobs: [] })),
  getQueueJob: vi.fn(() => Promise.resolve({})),
  setWorkers: vi.fn(() => Promise.resolve({ workers: 0 })),
}))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: Discover } = await import('./Discover.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container
}
const flush = async () => { await act(async () => {}) }
afterEach(() => { unmountAll(); checkReadiness.mockReset() })

describe('capacity-state notice', () => {
  it('shows "Preparing Discovery capacity" when capacity_state is starting', async () => {
    checkReadiness.mockResolvedValue({ ready: false, capacity_state: 'starting', degraded: ['no_workers'] })
    const c = await mount({})
    await flush()
    expect(c.textContent).toMatch(/Preparing Discovery capacity/i)
    expect(c.textContent).not.toMatch(/no_workers/)
  })

  it('shows "Discovery is temporarily unavailable" when capacity_state is unavailable', async () => {
    checkReadiness.mockResolvedValue({ ready: false, capacity_state: 'unavailable', degraded: ['worker_tier_never_started'] })
    const c = await mount({})
    await flush()
    expect(c.textContent).toMatch(/Discovery is temporarily unavailable/i)
    expect(c.textContent).not.toMatch(/worker_tier_never_started/)
  })

  it('shows "Discovery capacity is limited" when capacity_state is degraded', async () => {
    checkReadiness.mockResolvedValue({ ready: false, capacity_state: 'degraded', degraded: ['pdf_engine_missing'] })
    const c = await mount({})
    await flush()
    expect(c.textContent).toMatch(/Discovery capacity is limited/i)
  })

  it('falls back to "Preparing Discovery capacity" for legacy not-ready with no capacity_state', async () => {
    // Older /readyz responses without capacity_state — ready===false is treated as "starting"
    checkReadiness.mockResolvedValue({ ready: false, degraded: ['no_workers'] })
    const c = await mount({})
    await flush()
    expect(c.textContent).toMatch(/Preparing Discovery capacity/i)
    expect(c.textContent).not.toMatch(/no_workers/)
  })

  it('shows nothing when /readyz reports ready', async () => {
    checkReadiness.mockResolvedValue({ ready: true, capacity_state: 'ready', degraded: [] })
    const c = await mount({})
    await flush()
    expect(c.textContent).not.toMatch(/Preparing Discovery capacity/i)
    expect(c.textContent).not.toMatch(/Discovery is temporarily unavailable/i)
  })

  it('shows nothing while the probe is inconclusive (network error resolves null)', async () => {
    checkReadiness.mockResolvedValue(null)
    const c = await mount({})
    await flush()
    expect(c.textContent).not.toMatch(/Preparing Discovery capacity/i)
  })

  it('never shows while a scan is actively running', async () => {
    checkReadiness.mockResolvedValue({ ready: false, capacity_state: 'starting', degraded: ['no_workers'] })
    const c = await mount({ busy: true })
    await flush()
    expect(c.textContent).not.toMatch(/Preparing Discovery capacity/i)
  })

  it('does not block a scan in starting state — the queue is durable, and it never had a gate here', async () => {
    // This used to read the "Re-scan all sources" button and assert it was NOT disabled: a
    // capacity warning is information, not a block, because a queued job survives a cold worker
    // pool. That button was removed from Discover on 2026-09-02 (PRD "ACP Discover and Overview
    // Simplification"), so the guarantee is now that the warning renders WITHOUT disabling
    // anything on the screen — there is nothing here left to disable.
    checkReadiness.mockResolvedValue({ ready: false, capacity_state: 'starting', degraded: ['no_workers'] })
    const c = await mount({})
    await flush()
    expect(c.textContent).toMatch(/Preparing Discovery capacity/i)
    expect([...c.querySelectorAll('button')].find((b) => /Re-scan all sources/.test(b.textContent))).toBeUndefined()
    // Not one control on the screen was disabled by the capacity read.
    expect([...c.querySelectorAll('button')].filter((b) => b.disabled)).toEqual([])
  })
})
