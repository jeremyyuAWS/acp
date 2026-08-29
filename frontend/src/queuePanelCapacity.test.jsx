/**
 * QueuePanel's Azure Container App visibility (Monitor → Workers & Queue) — the same
 * getWorkerReplicas/getWorkerCapacity signals Discover's WorkerAvailability strip already shows
 * for a single active scan, brought here so the estate-wide operational view isn't blind to
 * Azure the way it was before this. Deliberately READ-ONLY: monitorWorkersQueue.test.jsx already
 * pins "points to Settings for capacity changes rather than duplicating the control here", so
 * this file must never assert a +/- button exists in QueuePanel.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
const getWorkerReplicas = vi.fn()
const getWorkerCapacity = vi.fn()
vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  setWorkers: vi.fn(),
  clearDeadJobs: vi.fn(),
  getWorkerReplicas: (...a) => getWorkerReplicas(...a),
  setWorkerReplicas: vi.fn(),
  getWorkerCapacity: (...a) => getWorkerCapacity(...a),
}))

const { default: QueuePanel } = await import('./QueuePanel.jsx')

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(QueuePanel)) })
  return container
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }

beforeEach(() => {
  getWorkerReplicas.mockResolvedValue({ configured: false, min_replicas: null, max_replicas: null })
  getWorkerCapacity.mockResolvedValue({ configured: false, current_replicas: null, cpu_percent: null,
                                        memory_percent: null, metrics_available: false })
})
afterEach(() => {
  unmountAll()
  getJobs.mockReset(); getWorkerReplicas.mockReset(); getWorkerCapacity.mockReset()
})

const distributed = { workers: 0, worker_tier_alive: true, runtime_mode: 'distributed', stats: {}, jobs: [] }
const auto = { workers: 3, worker_tier_alive: true, runtime_mode: 'auto', stats: {}, jobs: [] }

describe('QueuePanel Azure visibility', () => {
  it('does not fetch Azure data at all in the ordinary in-process (auto) runtime mode', async () => {
    getJobs.mockResolvedValue(auto)
    await mount()
    await settle()
    expect(getWorkerReplicas).not.toHaveBeenCalled()
    expect(getWorkerCapacity).not.toHaveBeenCalled()
  })

  it('shows the Azure warm-replica count once the tier reports distributed', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/Azure warm replicas: 2 \(max 5\)/)
  })

  it('shows current replicas + CPU/memory once capacity data resolves', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 2, cpu_percent: 18,
                                          memory_percent: 33, metrics_available: true })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/2 replicas running now/)
    expect(c.textContent).toMatch(/CPU 18%/)
    expect(c.textContent).toMatch(/Memory 33%/)
  })

  it('falls back to the generic "managed by" line before replicas has loaded', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockReturnValue(new Promise(() => {}))
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/managed by your deployment administrator/i)
  })

  it('never renders a +/- adjust control here — that stays in Settings → Worker Configuration', async () => {
    getJobs.mockResolvedValue(distributed)
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount()
    await settle()
    expect(c.querySelector('button[aria-label="Add a warm replica"]')).toBeFalsy()
    expect(c.querySelector('button[aria-label="Remove a warm replica"]')).toBeFalsy()
  })

  it('renders nothing extra for the in-process (non-distributed) worker mode', async () => {
    getJobs.mockResolvedValue(auto)
    const c = await mount()
    await settle()
    expect(c.textContent).not.toMatch(/Azure warm replicas/)
    expect(c.textContent).not.toMatch(/managed by your deployment administrator/i)
  })
})
