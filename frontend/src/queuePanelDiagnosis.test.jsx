import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Monitor -> Workers & Queue is the estate-wide operational view — until now it had no
// interpretive "why" text at all, not even a queue-stall check (WorkerAvailability.jsx has had
// one since #935/#936). This proves workerDiagnosis.js is actually wired into QueuePanel and
// runs across BOTH runtime modes, not just the distributed/Azure one that already gets the
// separate replica/capacity display.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
const setWorkers = vi.fn()
const clearDeadJobs = vi.fn()
const getWorkerReplicas = vi.fn()
const getWorkerCapacity = vi.fn()
vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  setWorkers: (...a) => setWorkers(...a),
  clearDeadJobs: (...a) => clearDeadJobs(...a),
  getWorkerReplicas: (...a) => getWorkerReplicas(...a),
  getWorkerCapacity: (...a) => getWorkerCapacity(...a),
}))

// jobsFeed.js shares ONE GET /jobs subscription across every component that wants it, and keeps
// its cached payload across unmount on purpose: a remount seconds later should draw immediately,
// and the payload carries its real fetchedAt plus a `stale` flag so it cannot pass as fresh.
// Within a test file that means one test's cache would otherwise answer the next test's mock.
// Reset it explicitly here — the module's production behaviour is deliberate and is covered in
// jobsFeed.test.js; it is this file that needs a cold start, not the cache that needs weakening.
import { resetJobsFeed } from './jobsFeed.js'
beforeEach(() => { resetJobsFeed() })


const { default: QueuePanel } = await import('./QueuePanel.jsx')

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(QueuePanel)) })
  return container
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }

afterEach(async () => {
  unmountAll()
  getJobs.mockReset(); setWorkers.mockReset(); clearDeadJobs.mockReset()
  getWorkerReplicas.mockReset(); getWorkerCapacity.mockReset()
  // getWorkerCapacity now goes through workerCapacityStore.js's shared singleton (also polled by
  // Discover.jsx) — reset so a later test's fresh mock isn't masked by an earlier test's cache.
  const { _resetForTests } = await import('./workerCapacityStore.js')
  _resetForTests()
})

const baseJobs = { workers: 4, worker_tier_alive: true, runtime_mode: 'auto', stats: { done: 0 },
                   recent: [], oldest_queued: null, worker_heartbeat_age_s: 5 }

describe('QueuePanel worker-health diagnosis', () => {
  it('shows nothing extra when everything is healthy', async () => {
    getJobs.mockResolvedValue(baseJobs)
    const c = await mount()
    await settle()
    expect(c.querySelector('[role="alert"]')).toBeFalsy()
  })

  it('diagnoses a never-reported-in worker tier in the ordinary in-process mode, not just distributed', async () => {
    getJobs.mockResolvedValue({ ...baseJobs, worker_tier_alive: false, worker_heartbeat_age_s: null })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/No worker has ever reported in/)
    expect(getWorkerReplicas).not.toHaveBeenCalled()
  })

  it('diagnoses a stale heartbeat with an explicit age', async () => {
    getJobs.mockResolvedValue({ ...baseJobs, worker_tier_alive: false, worker_heartbeat_age_s: 300 })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/hasn't reported in for 300s/)
  })

  it('diagnoses a stalled queue from oldest_queued', async () => {
    const stale = new Date(Date.now() - 120_000).toISOString()
    getJobs.mockResolvedValue({ ...baseJobs, oldest_queued: { id: 'j1', type: 'scan_discover', created_at: stale } })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/may not be actually claiming work/)
  })

  it('diagnoses an unhealthy Azure revision in distributed mode, using the same capacity fetch already shown', async () => {
    getJobs.mockResolvedValue({ ...baseJobs, runtime_mode: 'distributed' })
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 2, revision_health: 'Unhealthy',
                                          revision_provisioning_state: 'Provisioned', metrics_available: false })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/reporting Unhealthy/)
  })

  it('renders the alert role for a critical diagnosis', async () => {
    getJobs.mockResolvedValue({ ...baseJobs, worker_tier_alive: false, worker_heartbeat_age_s: null })
    const c = await mount()
    await settle()
    expect(c.querySelector('[role="alert"]')).toBeTruthy()
  })

  it('does not crash or diagnose anything before getJobs has resolved', async () => {
    getJobs.mockReturnValue(new Promise(() => {}))
    const c = await mount()
    await settle()
    expect(c.querySelector('[role="alert"]')).toBeFalsy()
  })
})
