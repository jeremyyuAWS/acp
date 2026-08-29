import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Proves Discover actually wires live getJobs()-derived worker counts into WorkerAvailability —
// mirrors processingStatusPanelIntegration.test.jsx's own SOURCE/DOM/unit split for AssessRunner.
// The point of this strip (unlike ProcessingStatusPanel, which only appears once a scan is
// active/terminal) is that it is visible the WHOLE time this tab is mounted — a user should be
// able to tell whether anything would pick up a job BEFORE they click "Re-scan".

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
// getWorkerCapacity defaults to a safe "not configured" response so every existing test in this
// file — none of which know or care about capacity evidence — keeps working unchanged; only the
// capacity-specific describe block below overrides it per test.
beforeEach(() => {
  getWorkerCapacity.mockResolvedValue({ configured: false, current_replicas: null,
                                        cpu_percent: null, memory_percent: null, metrics_available: false })
})
afterEach(async () => {
  unmountAll()
  getJobs.mockReset(); setWorkers.mockReset()
  getWorkerReplicas.mockReset(); setWorkerReplicas.mockReset()
  getWorkerCapacity.mockReset()
  // getWorkerCapacity now goes through workerCapacityStore.js's shared singleton (Discover.jsx
  // and QueuePanel.jsx poll the same cache) — without this reset, a later test's fresh
  // getWorkerCapacity.mockResolvedValue(...) can be masked by an earlier test's still-cached
  // value, since unmountAll()'s cleanup effect runs asynchronously relative to this afterEach.
  const { _resetForTests } = await import('./workerCapacityStore.js')
  _resetForTests()
})

describe('Worker availability on Discover', () => {
  it('shows the live worker count and online status from getJobs(), even with no scan running', async () => {
    getJobs.mockResolvedValue({ workers: 3, worker_tier_alive: true, suggested_workers: 4, runtime_mode: 'auto' })
    const c = await mount({})
    await settle()
    expect(c.textContent).toMatch(/online/i)
    expect(c.textContent).toMatch(/3 workers available to pick up jobs/i)
  })

  it('shows offline with zero workers when the worker tier has no heartbeat', async () => {
    getJobs.mockResolvedValue({ workers: 0, worker_tier_alive: false, suggested_workers: 4, runtime_mode: 'auto' })
    const c = await mount({})
    await settle()
    expect(c.textContent).toMatch(/offline/i)
    expect(c.textContent).toMatch(/processing capacity is off/i)
  })

  it('starting workers from zero calls setWorkers with the suggested count and reflects the result', async () => {
    getJobs.mockResolvedValue({ workers: 0, worker_tier_alive: false, suggested_workers: 4, runtime_mode: 'auto' })
    setWorkers.mockResolvedValue({ workers: 4 })
    const c = await mount({})
    await settle()
    const plus = c.querySelector('button[aria-label="Add a worker"]')
    await act(async () => { plus.click() })
    await settle()
    expect(setWorkers).toHaveBeenCalledWith(4)
    expect(c.textContent).toMatch(/4 workers available to pick up jobs/i)
  })

  it('renders nothing from this strip while getJobs has not resolved yet', async () => {
    getJobs.mockReturnValue(new Promise(() => {}))
    const c = await mount({})
    await settle()
    expect(c.textContent).not.toMatch(/available to pick up jobs/i)
  })

  it('threads oldest_queued.created_at through to the stall warning', async () => {
    const stale = new Date(Date.now() - 150_000).toISOString()
    getJobs.mockResolvedValue({ workers: 4, worker_tier_alive: true, suggested_workers: 4,
                                runtime_mode: 'auto', oldest_queued: { id: 'j1', type: 'scan_discover',
                                created_at: stale } })
    const c = await mount({})
    await settle()
    expect(c.textContent).toMatch(/may not be actually claiming work/i)
  })

  it('shows no stall warning when getJobs reports no queued job', async () => {
    getJobs.mockResolvedValue({ workers: 4, worker_tier_alive: true, suggested_workers: 4,
                                runtime_mode: 'auto', oldest_queued: null })
    const c = await mount({})
    await settle()
    expect(c.textContent).not.toMatch(/may not be actually claiming work/i)
  })
})

// GET /control/workers/replicas is open to any signed-in user — Discover must fetch and show it
// for everyone once the tier reports 'distributed', but only pass the adjust handler down to
// WorkerAvailability for me?.is_admin, matching the endpoint's own PATCH-only admin gate.
describe('Azure replica visibility/control wiring on Discover', () => {
  const distributed = { workers: 8, worker_tier_alive: true, suggested_workers: 4, runtime_mode: 'distributed' }

  it('does not call getWorkerReplicas at all in the ordinary in-process (auto) runtime mode', async () => {
    getJobs.mockResolvedValue({ workers: 3, worker_tier_alive: true, suggested_workers: 4, runtime_mode: 'auto' })
    const c = await mount({})
    await settle()
    expect(getWorkerReplicas).not.toHaveBeenCalled()
    void c
  })

  it('fetches and shows the Azure replica count for a non-admin once the tier is distributed', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    await settle()
    expect(getWorkerReplicas).toHaveBeenCalled()
    expect(c.textContent).toMatch(/Azure warm replicas: 2 \(max 5\)/)
    expect(c.querySelector('button[aria-label="Add a warm replica"]')).toBeFalsy()
  })

  it('gives an admin +/- controls that call setWorkerReplicas and reflect the result', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    setWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 3, max_replicas: 5 })
    const c = await mount({ me: { email: 'admin@b.com', is_admin: true } })
    await settle()
    const plus = c.querySelector('button[aria-label="Add a warm replica"]')
    expect(plus).toBeTruthy()
    await act(async () => { plus.click() })
    await settle()
    expect(setWorkerReplicas).toHaveBeenCalledWith(3)
    expect(c.textContent).toMatch(/Azure warm replicas: 3 \(max 5\)/)
  })

  it('a non-admin sees the generic "managed by" line, never the count, while replicas has not resolved', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockReturnValue(new Promise(() => {}))
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    await settle()
    expect(c.textContent).toMatch(/managed by your deployment administrator/i)
  })
})

// GET /jobs' worker_heartbeat_age_s (2026-08-29) — the third of the PRD's three freshness
// timestamps, threaded from getJobs() into workerSnap into the processing panel's own facts.
describe('Worker-heartbeat freshness wired into the processing panel', () => {
  it('shows "Worker heartbeat" once getJobs reports a heartbeat age, while a scan is busy', async () => {
    getJobs.mockResolvedValue({ workers: 4, worker_tier_alive: true, suggested_workers: 4,
                                runtime_mode: 'auto', worker_heartbeat_age_s: 7 })
    const c = await mount({ busy: true, progress: { phase: 'discovering' } })
    await settle()
    expect(c.textContent).toMatch(/Worker heartbeat/)
    expect(c.textContent).toMatch(/7s ago/)
  })

  it('shows nothing for worker heartbeat when getJobs reports none', async () => {
    getJobs.mockResolvedValue({ workers: 4, worker_tier_alive: true, suggested_workers: 4,
                                runtime_mode: 'auto', worker_heartbeat_age_s: null })
    const c = await mount({ busy: true, progress: { phase: 'discovering' } })
    await settle()
    expect(c.textContent).not.toMatch(/Worker heartbeat/)
  })
})

// GET /control/workers/capacity is a SEPARATE fetch from GET /control/workers/replicas — current
// replica count and CPU/memory, not the configured min/max. Same visibility rule: open to
// everyone, only fetched once the tier reports 'distributed', no admin gate at all (there's
// nothing to mutate here, unlike replicas).
describe('Azure capacity-evidence wiring on Discover', () => {
  const distributed = { workers: 8, worker_tier_alive: true, suggested_workers: 4, runtime_mode: 'distributed' }

  it('does not call getWorkerCapacity in the ordinary in-process (auto) runtime mode', async () => {
    getJobs.mockResolvedValue({ workers: 3, worker_tier_alive: true, suggested_workers: 4, runtime_mode: 'auto' })
    const c = await mount({})
    await settle()
    expect(getWorkerCapacity).not.toHaveBeenCalled()
    void c
  })

  it('fetches and shows current replicas + CPU/memory once the tier is distributed, for a non-admin too', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 2, cpu_percent: 18,
                                          memory_percent: 33, metrics_available: true })
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    await settle()
    expect(getWorkerCapacity).toHaveBeenCalled()
    expect(c.textContent).toMatch(/2 replicas running now/)
    expect(c.textContent).toMatch(/CPU 18%/)
    expect(c.textContent).toMatch(/Memory 33%/)
  })

  it('shows nothing extra while capacity has not resolved yet, without blocking the replicas line', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    getWorkerCapacity.mockReturnValue(new Promise(() => {}))
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    await settle()
    expect(c.textContent).toMatch(/Azure warm replicas: 2 \(max 5\)/)
    expect(c.textContent).not.toMatch(/running now/)
  })

  it('a network failure leaves capacity silently unset rather than crashing the tab', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    getWorkerCapacity.mockRejectedValue(new Error('network error'))
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    await settle()
    expect(c.textContent).toMatch(/Azure warm replicas: 2 \(max 5\)/)
    expect(c.textContent).not.toMatch(/running now/)
  })
})

// Revision health + draining replicas (2026-08-29) — the third capacity fact, threaded through
// the SAME GET /control/workers/capacity fetch, visible to everyone (no admin gate, matching
// current_replicas/cpu_percent/memory_percent above).
describe('Azure revision-health wiring on Discover', () => {
  const distributed = { workers: 8, worker_tier_alive: true, suggested_workers: 4, runtime_mode: 'distributed' }

  it('shows the active revision health and draining-replica count for a non-admin', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 3, cpu_percent: 20,
                                          memory_percent: 40, metrics_available: true,
                                          revision_health: 'Healthy', revision_provisioning_state: 'Provisioned',
                                          draining_replicas: 2 })
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    await settle()
    expect(c.textContent).toMatch(/Revision healthy/)
    expect(c.textContent).toMatch(/2 replicas draining from an older revision/)
  })

  it('omits the draining line entirely when nothing is draining', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 3, cpu_percent: null,
                                          memory_percent: null, metrics_available: false,
                                          revision_health: 'Healthy', revision_provisioning_state: 'Provisioned',
                                          draining_replicas: 0 })
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    await settle()
    expect(c.textContent).toMatch(/Revision healthy/)
    expect(c.textContent).not.toMatch(/draining/)
  })

  it('omits revision health entirely when the backend could not read it', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 3, cpu_percent: null,
                                          memory_percent: null, metrics_available: false,
                                          revision_health: null, revision_provisioning_state: null,
                                          draining_replicas: null })
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    await settle()
    expect(c.textContent).not.toMatch(/Revision/)
    expect(c.textContent).not.toMatch(/draining/)
  })
})
