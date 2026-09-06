/**
 * The Live Operations capacity-mode strip — the read-only half of PRD review finding R1.
 *
 * The strip answers "which capacity mode are we in, and when does it change?" where operators
 * are already looking, WITHOUT becoming a second place capacity can be changed. Both halves are
 * asserted here, because either one alone is the wrong feature: a strip with a control violates
 * the split the repository already enforces, and a strip that renders a PROPOSED schedule beside
 * live traffic gets read as describing that traffic.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const snapshot = vi.hoisted(() => ({ current: null }))
vi.mock('./api.js', () => ({
  getCapacitySchedule: () => (snapshot.current instanceof Error
    ? Promise.reject(snapshot.current)
    : Promise.resolve(snapshot.current)),
}))

import CapacityModeStrip from './CapacityModeStrip.jsx'

const APPLIED = {
  applied: true,
  enabled: true,
  timezone: 'America/Los_Angeles',
  effective_mode: 'business_hours',
  next_transition_at: '2026-09-08T03:00:00+00:00',
  next_transition_to: 'off_hours',
  drift: [],
  drift_evaluated: true,
}

async function mount(data) {
  snapshot.current = data
  const host = document.createElement('div')
  document.body.appendChild(host)
  await act(async () => { createRoot(host).render(<CapacityModeStrip />) })
  await act(async () => { await Promise.resolve() })
  return host
}

beforeEach(() => { document.body.innerHTML = '' })

describe('the strip shows the live capacity mode', () => {
  it('names the mode, the timezone and the next change', async () => {
    const c = await mount(APPLIED)
    expect(c.textContent).toContain('Business-hours capacity')
    expect(c.textContent).toContain('America/Los_Angeles')
    expect(c.textContent).toMatch(/next change/)
  })

  it('names off-hours capacity too', async () => {
    const c = await mount({ ...APPLIED, effective_mode: 'off_hours' })
    expect(c.textContent).toContain('Off-hours capacity')
  })

  it('surfaces drift where the replica counts are being read', async () => {
    const c = await mount({ ...APPLIED, drift: [
      { app: 'acp-assess', field: 'max_replicas', desired: 10, observed: 5 },
    ] })
    expect(c.textContent).toMatch(/configuration drift on 1 setting\b/)
  })

  it('points at Settings rather than offering the control here', async () => {
    const c = await mount(APPLIED)
    expect(c.textContent).toMatch(/Settings . Scheduling/)
    // The invariant queuePanelCapacity.test.jsx holds for the queue panel, held here too: this
    // surface reports capacity, it never changes it.
    expect(c.querySelectorAll('button').length).toBe(0)
    expect(c.querySelectorAll('input').length).toBe(0)
  })
})

describe('the strip stays silent rather than describing live traffic wrongly', () => {
  it('renders nothing while the schedule is only proposed', async () => {
    // `applied`, not `enabled`: a proposal can be enabled and still be in force nowhere, and the
    // figures beside this strip in Live Operations are all real.
    const c = await mount({ ...APPLIED, applied: false })
    expect(c.textContent).toBe('')
  })

  it('renders nothing when the schedule cannot be read', async () => {
    const c = await mount(new Error('boom'))
    expect(c.textContent).toBe('')
  })

  it('renders nothing rather than throwing when the fetch helper is missing entirely', async () => {
    // Not a hypothetical: AdminLiveTraffic's own tests mock ./api.js explicitly, and a helper
    // that is absent throws SYNCHRONOUSLY — no promise, so no .catch. Before the strip guarded
    // that, mounting it took the whole Live Operations view to the ErrorBoundary: the
    // infrastructure map, the worker services and the running-jobs list, lost to one status
    // line. A strip is decoration relative to the map it sits above.
    const mod = await import('./api.js')
    const original = mod.getCapacitySchedule
    try {
      mod.getCapacitySchedule = undefined
      const host = document.createElement('div')
      document.body.appendChild(host)
      await act(async () => { createRoot(host).render(<CapacityModeStrip />) })
      expect(host.textContent).toBe('')
    } finally {
      mod.getCapacitySchedule = original
    }
  })

  it('does not claim drift it was never able to evaluate', async () => {
    const c = await mount({ ...APPLIED, drift_evaluated: false,
      drift: [{ app: 'acp-assess', field: 'max_replicas', desired: 10, observed: 5 }] })
    expect(c.textContent).not.toMatch(/drift/)
  })
})
