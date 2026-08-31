import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Pure presentational tests for WorkerAvailability — the "how many workers are available to
// pick up scan jobs" strip extracted from AssessRunner's worker strip so Discover (and later
// Remediate) can show the same signal without re-deriving it. DOM wiring into Discover is
// covered separately in discoverWorkerAvailability.test.jsx.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: WorkerAvailability } = await import('./WorkerAvailability.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(WorkerAvailability, props)) })
  return container
}
afterEach(unmountAll)

describe('WorkerAvailability', () => {
  it('renders nothing when no snapshot has loaded yet', async () => {
    const c = await mount({ snap: null })
    expect(c.textContent).toBe('')
  })

  it('shows the worker service online and the worker count', async () => {
    const c = await mount({ snap: { workers: 3, alive: true } })
    expect(c.textContent).toMatch(/online/i)
    expect(c.textContent).toMatch(/3 workers available to pick up jobs/i)
  })

  it('shows offline when the worker tier has no live heartbeat', async () => {
    const c = await mount({ snap: { workers: 0, alive: false } })
    expect(c.textContent).toMatch(/offline/i)
    expect(c.textContent).toMatch(/processing capacity is off/i)
    expect(c.textContent).toMatch(/no worker will pick up new jobs/i)
  })

  it('does not say "online" and "0 workers available" in the same breath — that reads as a '
     + 'contradiction (found live 2026-08-29); zero capacity is said as one fact instead', async () => {
    const c = await mount({ snap: { workers: 0, alive: true } })
    expect(c.textContent).toMatch(/online/i)
    expect(c.textContent).not.toMatch(/0 workers available/i)
  })

  it('does not claim "no worker will pick up new jobs" when the dedicated worker tier is alive '
     + '— found live 2026-08-30, a false alarm on every split-topology deployment with the '
     + 'in-process pool left at its default of 0', async () => {
    const c = await mount({ snap: { workers: 0, alive: true } })
    expect(c.textContent).not.toMatch(/no worker will pick up new jobs/i)
    expect(c.textContent).toMatch(/jobs run on the dedicated stage service/i)
  })


  it('singularizes "worker" for a count of one', async () => {
    const c = await mount({ snap: { workers: 1, alive: true } })
    expect(c.textContent).toMatch(/1 worker available to pick up jobs/i)
  })

  it('does not expose manual concurrency controls; stage capacity is managed automatically', async () => {
    const c = await mount({ snap: { workers: 0, alive: true }, onAdjust: vi.fn() })
    expect(c.querySelector('button[aria-label="Remove a worker"]')).toBeFalsy()
    expect(c.querySelector('button[aria-label="Add a worker"]')).toBeFalsy()
    expect(c.textContent).toMatch(/capacity is managed automatically/i)
  })

  it('hides the +/- controls and explains externally-managed capacity for a distributed alive tier', async () => {
    const c = await mount({ snap: { workers: 8, alive: true, runtime_mode: 'distributed' }, onAdjust: vi.fn() })
    expect(c.querySelector('button[aria-label="Add a worker"]')).toBeFalsy()
    expect(c.textContent).toMatch(/managed by your deployment administrator/i)
  })

  it('does not render +/- controls when no onAdjust is given', async () => {
    const c = await mount({ snap: { workers: 2, alive: true } })
    expect(c.querySelector('button[aria-label="Add a worker"]')).toBeFalsy()
  })
})

// GET /control/workers/replicas is open to every signed-in user (not admin-gated) — visibility
// is for everyone, only the +/- adjust action is admin-only. This component never checks a role
// itself; it goes purely by whether onAdjustReplicas was passed, mirroring onAdjust above.
describe('WorkerAvailability Azure replica visibility (externally-managed tier)', () => {
  const distributedSnap = { workers: 8, alive: true, runtime_mode: 'distributed' }

  it('shows the Azure warm-replica count instead of the generic "managed by" line once loaded', async () => {
    const c = await mount({ snap: distributedSnap,
                             replicas: { configured: true, min_replicas: 2, max_replicas: 5 } })
    expect(c.textContent).toMatch(/Azure warm replicas: 2 \(max 5\)/)
    expect(c.textContent).not.toMatch(/managed by your deployment administrator/i)
  })

  it('falls back to the generic "managed by" line before replicas has loaded', async () => {
    const c = await mount({ snap: distributedSnap, replicas: null })
    expect(c.textContent).toMatch(/managed by your deployment administrator/i)
  })

  it('falls back to the generic line when Azure is not configured on the backend', async () => {
    const c = await mount({ snap: distributedSnap,
                             replicas: { configured: false, min_replicas: null, max_replicas: null } })
    expect(c.textContent).toMatch(/managed by your deployment administrator/i)
  })

  it('a non-admin (no onAdjustReplicas) sees the count but no adjust buttons', async () => {
    const c = await mount({ snap: distributedSnap,
                             replicas: { configured: true, min_replicas: 2, max_replicas: 5 } })
    expect(c.textContent).toMatch(/Azure warm replicas: 2/)
    expect(c.querySelector('button[aria-label="Add a warm replica"]')).toBeFalsy()
    expect(c.querySelector('button[aria-label="Remove a warm replica"]')).toBeFalsy()
  })

  it('an admin (onAdjustReplicas given) gets +/- buttons that call it, bounded to 1–5', async () => {
    const onAdjustReplicas = vi.fn()
    const c = await mount({ snap: distributedSnap, onAdjustReplicas,
                             replicas: { configured: true, min_replicas: 1, max_replicas: 5 } })
    const minus = c.querySelector('button[aria-label="Remove a warm replica"]')
    const plus = c.querySelector('button[aria-label="Add a warm replica"]')
    expect(minus.disabled).toBe(true)    // already at the floor
    expect(plus.disabled).toBe(false)
    await act(async () => { plus.click() })
    expect(onAdjustReplicas).toHaveBeenCalledWith(1)
  })

  it('disables both replica buttons at the ceiling and while an adjustment is in flight', async () => {
    const c = await mount({ snap: distributedSnap, onAdjustReplicas: vi.fn(), replicasBusy: false,
                             replicas: { configured: true, min_replicas: 5, max_replicas: 5 } })
    expect(c.querySelector('button[aria-label="Add a warm replica"]').disabled).toBe(true)
    const busy = await mount({ snap: distributedSnap, onAdjustReplicas: vi.fn(), replicasBusy: true,
                                replicas: { configured: true, min_replicas: 2, max_replicas: 5 } })
    expect(busy.querySelector('button[aria-label="Add a warm replica"]').disabled).toBe(true)
    expect(busy.querySelector('button[aria-label="Remove a warm replica"]').disabled).toBe(true)
  })

  it('shows the transient replicasMsg feedback when set', async () => {
    const c = await mount({ snap: distributedSnap, onAdjustReplicas: vi.fn(),
                             replicasMsg: 'Warm replicas set to 3',
                             replicas: { configured: true, min_replicas: 3, max_replicas: 5 } })
    expect(c.textContent).toMatch(/Warm replicas set to 3/)
  })
})

// "online, but nothing is actually draining the queue" — the gap both #935 and #936 found live
// 2026-08-29 (a worker pool silently booted at zero threads; a Drive client with no socket
// timeout that could hang a claimed job forever). Both looked identical to "online" from the
// heartbeat alone; this is what makes that gap visible on screen instead of only in code.
describe('WorkerAvailability queue-stall warning', () => {
  it('is silent when alive and nothing is queued', async () => {
    const c = await mount({ snap: { workers: 4, alive: true, oldestQueuedCreatedAt: null } })
    expect(c.textContent).not.toMatch(/may not be actually claiming work/i)
  })

  it('is silent when alive and the oldest queued job is recent', async () => {
    const recent = new Date(Date.now() - 5_000).toISOString()
    const c = await mount({ snap: { workers: 4, alive: true, oldestQueuedCreatedAt: recent } })
    expect(c.textContent).not.toMatch(/may not be actually claiming work/i)
  })

  it('warns when alive but a queued job has waited past the stall threshold', async () => {
    const stale = new Date(Date.now() - 120_000).toISOString()
    const c = await mount({ snap: { workers: 4, alive: true, oldestQueuedCreatedAt: stale } })
    expect(c.textContent).toMatch(/reports online, but a queued job has been waiting 120s/i)
    expect(c.textContent).toMatch(/may not be actually claiming work/i)
    expect(c.querySelector('[role="alert"]')).toBeTruthy()
  })

  it('does not warn when offline — that is already a separate, visible problem', async () => {
    const stale = new Date(Date.now() - 120_000).toISOString()
    const c = await mount({ snap: { workers: 0, alive: false, oldestQueuedCreatedAt: stale } })
    expect(c.textContent).toMatch(/offline/i)
    expect(c.textContent).not.toMatch(/may not be actually claiming work/i)
  })
})

// GET /control/workers/capacity is a SEPARATE question from replicas above — that's the
// configured min/max; this is what Azure has actually provisioned and how loaded it is. No
// admin gate anywhere (read-only, same as `replicas`), and individual fields degrade to
// omitted-not-fabricated when the backend couldn't measure them.
describe('WorkerAvailability capacity evidence (current replicas, CPU/memory)', () => {
  const distributedSnap = { workers: 8, alive: true, runtime_mode: 'distributed' }

  it('shows current replica count and CPU/memory when the backend has all of it', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 2, cpu_percent: 23.5, memory_percent: 40,
                  metrics_available: true },
    })
    expect(c.textContent).toMatch(/2 replicas running now/)
    expect(c.textContent).toMatch(/CPU 23\.5%/)
    expect(c.textContent).toMatch(/Memory 40%/)
  })

  it('singularizes "replica" for a count of one', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 1, cpu_percent: null, memory_percent: null,
                  metrics_available: false },
    })
    expect(c.textContent).toMatch(/1 replica running now/)
    expect(c.textContent).not.toMatch(/1 replicas/)
  })

  it('shows replica count alone when metrics are unavailable, not a fabricated 0%', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false },
    })
    expect(c.textContent).toMatch(/3 replicas running now/)
    expect(c.textContent).not.toMatch(/CPU/)
    expect(c.textContent).not.toMatch(/Memory/)
  })

  it('renders nothing extra when capacity has not loaded yet', async () => {
    const c = await mount({ snap: distributedSnap, capacity: null })
    expect(c.textContent).not.toMatch(/running now/)
  })

  it('renders nothing extra when Azure capacity reporting is not configured', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: false, current_replicas: null, cpu_percent: null,
                  memory_percent: null, metrics_available: false },
    })
    expect(c.textContent).not.toMatch(/running now/)
  })

  it('renders nothing extra for the in-process (non-distributed) worker mode', async () => {
    const c = await mount({
      snap: { workers: 3, alive: true, runtime_mode: 'auto' },
      capacity: { configured: true, current_replicas: 2, cpu_percent: 10, memory_percent: 20,
                  metrics_available: true },
    })
    expect(c.textContent).not.toMatch(/running now/)
  })
})

// Revision health + draining replicas (2026-08-29) — the practical "is a rollout mid-drain"
// signal, a THIRD independent Azure call alongside min/max and current_replicas/metrics above,
// so it degrades to null on its own rather than hiding data the other two calls already got.
describe('WorkerAvailability revision health and draining replicas', () => {
  const distributedSnap = { workers: 8, alive: true, runtime_mode: 'distributed' }

  it('shows a healthy active revision and how many replicas are draining off an old one', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: 'Healthy',
                  revision_provisioning_state: 'Provisioned', draining_replicas: 2 },
    })
    expect(c.textContent).toMatch(/Revision healthy/)
    expect(c.textContent).toMatch(/2 replicas draining from an older revision/)
  })

  it('singularizes the draining count', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: 'Healthy',
                  revision_provisioning_state: 'Provisioned', draining_replicas: 1 },
    })
    expect(c.textContent).toMatch(/1 replica draining/)
    expect(c.textContent).not.toMatch(/1 replicas draining/)
  })

  it('flags an unhealthy revision distinctly from a healthy one', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: 'Unhealthy',
                  revision_provisioning_state: 'Failed', draining_replicas: 0 },
    })
    expect(c.textContent).toMatch(/Revision unhealthy/)
  })

  it('omits the draining line when nothing is draining, without hiding revision health', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: 'Healthy',
                  revision_provisioning_state: 'Provisioned', draining_replicas: 0 },
    })
    expect(c.textContent).toMatch(/Revision healthy/)
    expect(c.textContent).not.toMatch(/draining/)
  })

  it('omits revision health entirely when the backend could not read it, without losing replica count', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: null,
                  revision_provisioning_state: null, draining_replicas: null },
    })
    expect(c.textContent).toMatch(/3 replicas running now/)
    expect(c.textContent).not.toMatch(/Revision/)
    expect(c.textContent).not.toMatch(/draining/)
  })
})

// Revision traffic-split (2026-08-29) — a revision can be Healthy and running replicas while
// still receiving 0% of ingress traffic (a real stuck-rollout incident on this app). A SEPARATE
// question from revision_health, so it needs its own display, not folded into that badge.
describe('WorkerAvailability revision traffic-split', () => {
  const distributedSnap = { workers: 8, alive: true, runtime_mode: 'distributed' }

  it('shows the active revision\'s traffic share', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: 'Healthy', draining_replicas: 0,
                  revision_traffic_percent: 80 },
    })
    expect(c.textContent).toMatch(/80% of traffic on the active revision/)
  })

  it('shows 0%, not nothing, for a stranded revision', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: 'Healthy', draining_replicas: 0,
                  revision_traffic_percent: 0 },
    })
    expect(c.textContent).toMatch(/0% of traffic on the active revision/)
  })

  it('omits the traffic line when the backend could not read it', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: 3, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: 'Healthy', draining_replicas: 0,
                  revision_traffic_percent: null },
    })
    expect(c.textContent).not.toMatch(/of traffic/)
  })

  it('renders the capacity block for traffic data alone, even with nothing else to show', async () => {
    const c = await mount({
      snap: distributedSnap,
      capacity: { configured: true, current_replicas: null, cpu_percent: null, memory_percent: null,
                  metrics_available: false, revision_health: null, draining_replicas: null,
                  revision_traffic_percent: 45 },
    })
    expect(c.textContent).toMatch(/45% of traffic on the active revision/)
  })
})
