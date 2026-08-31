/**
 * Azure evidence must stay visible when the worker tier is NOT alive.
 *
 * Discover and QueuePanel both gated their Azure reads on
 * `runtime_mode === 'distributed' && <tier is alive>`, conflating two different facts:
 *
 *   runtime_mode  — TOPOLOGY. Does this deployment run a separate, Azure-managed worker tier?
 *                   A configuration fact. It does not change when workers fall over.
 *   alive         — HEALTH. Is that tier heartbeating right now?
 *
 * With both in one condition, the UI stopped asking Azure anything the moment the heartbeat went
 * stale — so replica counts, draining replicas and revision health disappeared precisely when a
 * user needed them to understand why nothing was picking up their job. The evidence was gated on
 * the very condition it exists to explain.
 *
 * These tests pin the corrected split. They fail on the old gate: with `alive: false` the old
 * condition is false, so getWorkerReplicas/getWorkerCapacity are never called at all.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
const setWorkers = vi.fn()
const getWorkerReplicas = vi.fn()
const setWorkerReplicas = vi.fn()
const getWorkerCapacity = vi.fn()
vi.mock('./api.js', () => ({
  checkReadiness: vi.fn(() => Promise.resolve(null)),
  getScanInventory: vi.fn(() => Promise.resolve(null)),
  listScanDecisions: vi.fn(() => Promise.resolve([])),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
  getJobs: (...a) => getJobs(...a),
  setWorkers: (...a) => setWorkers(...a),
  getWorkerReplicas: (...a) => getWorkerReplicas(...a),
  setWorkerReplicas: (...a) => setWorkerReplicas(...a),
  getWorkerCapacity: (...a) => getWorkerCapacity(...a),
}))

import { resetJobsFeed } from './jobsFeed.js'

const { default: Discover } = await import('./Discover.jsx')

const mount = async (props = {}) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(Discover,
      { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container
}
const settle = async (n = 4) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

/** The distributed worker tier, with its heartbeat GONE — the situation that matters. */
const TIER_DOWN = {
  workers: 0,
  worker_tier_alive: false,
  worker_heartbeat_age_s: 240,
  suggested_workers: 4,
  runtime_mode: 'distributed',
  oldest_queued: { created_at: new Date().toISOString() },
  stats: { queued: 3, running: 0, done: 0 },
  dead_letters: { by_type: {}, top_errors: [] },
  jobs: [],
}

beforeEach(async () => {
  resetJobsFeed()
  getWorkerCapacity.mockResolvedValue({
    configured: true, current_replicas: 2, draining_replicas: 1,
    revision_health: 'Unhealthy', cpu_percent: 12, memory_percent: 40, metrics_available: true,
  })
  getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 3, max_replicas: 10 })
})

afterEach(async () => {
  unmountAll()
  getJobs.mockReset(); setWorkers.mockReset()
  getWorkerReplicas.mockReset(); setWorkerReplicas.mockReset(); getWorkerCapacity.mockReset()
  const { _resetForTests } = await import('./workerCapacityStore.js')
  _resetForTests()
  resetJobsFeed()
})

describe('Discover keeps observing Azure while the worker tier is down', () => {
  it('still asks Azure for the replica configuration', async () => {
    getJobs.mockResolvedValue(TIER_DOWN)
    await mount()
    await settle()
    expect(getWorkerReplicas).toHaveBeenCalled()
  })

  it('still asks Azure for capacity evidence', async () => {
    getJobs.mockResolvedValue(TIER_DOWN)
    await mount()
    await settle()
    expect(getWorkerCapacity).toHaveBeenCalled()
  })

  it('does NOT ask Azure when the deployment has no external worker tier at all', async () => {
    // The topology half of the condition still has to hold — an in-process deployment has no
    // Azure worker tier to describe, so asking would be noise, not evidence.
    getJobs.mockResolvedValue({ ...TIER_DOWN, runtime_mode: 'in-process' })
    await mount()
    await settle()
    expect(getWorkerReplicas).not.toHaveBeenCalled()
    expect(getWorkerCapacity).not.toHaveBeenCalled()
  })

  it('observes Azure while the tier is healthy too — the fix widens, never narrows', async () => {
    getJobs.mockResolvedValue({ ...TIER_DOWN, worker_tier_alive: true, workers: 12,
                                worker_heartbeat_age_s: 2 })
    await mount()
    await settle()
    expect(getWorkerReplicas).toHaveBeenCalled()
    expect(getWorkerCapacity).toHaveBeenCalled()
  })
})

describe('the gate reads topology, not health', () => {
  it('is written as runtime_mode alone in both components', async () => {
    const { readFileSync } = await import('node:fs')
    const { fileURLToPath } = await import('node:url')
    const { dirname, join } = await import('node:path')
    const here = dirname(fileURLToPath(import.meta.url))
    const discover = readFileSync(join(here, 'Discover.jsx'), 'utf8')
    const queue = readFileSync(join(here, 'QueuePanel.jsx'), 'utf8')

    expect(discover).toContain("const workerTierIsExternal = workerSnap?.runtime_mode === 'distributed'")
    expect(discover).not.toMatch(/runtime_mode === 'distributed' && workerSnap\?\.alive/)
    expect(queue).toContain("const externallyManaged = q?.runtime_mode === 'distributed'")
    expect(queue).not.toMatch(/runtime_mode === 'distributed' && q\?\.worker_tier_alive/)
  })
})
