/**
 * "Queue updated N seconds ago" must be the age of the DATA, not the age of the subscription.
 *
 * jobsFeed.js shares one GET /jobs across every consumer and deliberately keeps its payload across
 * unmount, so a remount draws immediately instead of re-fetching. That is only safe because the
 * feed hands every subscriber the REAL `fetchedAt` of the fetch that produced the payload,
 * alongside a `stale` flag — its own header says "Mounting must not make old data look new".
 *
 * Discover discarded that and stamped its own:
 *
 *     setQueueSnap({ …, polledAt: Date.now() })
 *
 * so the one surface that displays freshness reported the moment the callback ran. Mounting onto a
 * warm cache therefore rendered "Queue updated just now" for a payload that could be a minute old
 * and already flagged stale — the exact failure the feed was built to prevent, defeated at the
 * only call site that shows it. Shipped in #1054; this is the correction.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  checkReadiness: vi.fn(() => Promise.resolve(null)),
  getScanInventory: vi.fn(() => Promise.resolve(null)),
  listScanDecisions: vi.fn(() => Promise.resolve([])),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
  setWorkers: vi.fn(),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  getWorkerCapacity: vi.fn(() => Promise.resolve({ configured: false })),
  getQueueJob: vi.fn(() => Promise.resolve(null)),
  getQueueEstimate: vi.fn(() => Promise.resolve({ available: false })),
}))

import { resetJobsFeed, subscribeJobs } from './jobsFeed.js'
const { default: Discover } = await import('./Discover.jsx')

const QUEUED = {
  workers: 2, worker_tier_alive: true, worker_heartbeat_age_s: 3,
  suggested_workers: 4, runtime_mode: 'distributed',
  stats: { queued: 2, running: 0, done: 0 },
  dead_letters: { by_type: {}, top_errors: [] },
  jobs: [{ id: 'other', type: 'scan_discover' }],
}

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [], files: [], onScan: () => {},
      busy: true, progress: { phase: 'queued', started_at: new Date().toISOString() },
      jobId: 'mine', ...props }))
  })
  return container
}
const settle = async (n = 6) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

beforeEach(() => { resetJobsFeed(); getJobs.mockReset(); getJobs.mockResolvedValue(QUEUED) })
afterEach(() => { unmountAll(); resetJobsFeed(); vi.useRealTimers() })

describe('the queue card\'s freshness line', () => {
  it('reports the age of the data, not the age of the mount', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })

    // Warm the shared cache, then let time pass with nobody subscribed.
    const stop = subscribeJobs('queued', () => {}, { intervalMs: 600000 })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    stop()
    await act(async () => { await vi.advanceTimersByTimeAsync(45000) })

    // The revalidation the remount kicks off never lands. That is the window the defect lives
    // in — and it is the window that matters, because a slow or unreachable API is exactly when
    // a user needs to know the number on screen is a minute old rather than current. An earlier
    // draft of this test let the refetch resolve, so the data really WAS fresh and the assertion
    // was measuring the wrong thing.
    getJobs.mockImplementation(() => new Promise(() => {}))

    const container = await mount()
    await settle()

    const line = [...container.querySelectorAll('div')]
      .map((d) => d.textContent).find((t) => /^Queue updated /.test(t || ''))
    expect(line, 'expected the card to render its freshness line').toBeTruthy()
    // 45s-old data must not read as brand new. "just now"/"0s" would be the defect.
    expect(line).not.toMatch(/just now/i)
    expect(line).not.toMatch(/\b0s\b/)
  })

  it('still reports a fresh figure for a fetch that just happened', async () => {
    // The invariant: this must not become "always looks stale". Passes before AND after.
    const container = await mount()
    await settle()
    const line = [...container.querySelectorAll('div')]
      .map((d) => d.textContent).find((t) => /^Queue updated /.test(t || ''))
    expect(line).toBeTruthy()
    expect(line).not.toMatch(/\b\d{2,}m\b/)   // not minutes-old for a fetch made this tick
  })
})
