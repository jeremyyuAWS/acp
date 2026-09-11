/**
 * Settings → Scheduling, asserted at the DOM level.
 *
 * The panel is read-only, and most of what these tests hold is about what it must NOT let a
 * reader conclude. Three fields exist to prevent three specific wrong readings, and each is
 * easy to render into agreement by accident:
 *
 *   * a PROPOSED schedule must not look like a live one;
 *   * an empty drift list next to a visibly different Azure must not read as "they match";
 *   * a queue rule on a pinned tier must not read as healthy.
 *
 * The fourth thing held here is that the tab renders the refusal at all: the PRD's own capacity
 * table is over the connection budget, and a panel that showed the numbers without the verdict
 * would be the editor's worst possible precursor.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const snapshot = vi.hoisted(() => ({ current: null, calls: 0 }))
vi.mock('./api.js', () => ({
  getCapacitySchedule: () => (++snapshot.calls && snapshot.current instanceof Error
    ? Promise.reject(snapshot.current)
    : Promise.resolve(snapshot.current)),
}))

import CapacitySchedule from './CapacitySchedule.jsx'

const PROPOSED = {
  enabled: false,
  timezone: 'America/Los_Angeles',
  days: ['mon', 'tue', 'wed', 'thu', 'fri'],
  start: '06:00',
  end: '20:00',
  business_hours: { web: 2, discovery: 2, assess: 5, remediate: 5, gpu: 1 },
  off_hours: { web: 1, discovery: 1, assess: 1, remediate: 1, gpu: 0 },
  maximums: { web: 3, discovery: 4, assess: 10, remediate: 10, gpu: 1 },
  effective_mode: 'off_hours',
  next_transition_at: null,
  next_transition_to: null,
  version: 0,
  applied: false,
  validation: {
    schedule_valid: false,
    blocked: true,
    findings: [{ code: 'over_connection_budget', blocking: true,
                 detail: 'The fleet wants 152 connections during a revision overlap, plus 15 reserved, against a server that has 150. Over by 17.' }],
    capacity: { steady_connections: 96, deploy_connections: 152, reserve: 15,
                server_max_connections: 150, connection_headroom: -17,
                vcpu_demand: 71.0, vcpu_quota: null },
  },
  scalers: {
    discovery: { app: 'acp-discovery', state: 'missing', rules: [],
                 detail: 'acp-discovery can scale to 6 but carries no queue rule, so nothing asks it to.' },
    assess: { app: 'acp-assess', state: 'pinned', rules: ['assess-queue'],
              detail: 'acp-assess is pinned at 5: a queue rule attached to it cannot add a replica.' },
    remediate: { app: 'acp-remediate', state: 'healthy', rules: ['remediation-queue'] },
  },
  observed: {
    'acp-assess': { min_replicas: 5, max_replicas: 5, current_replicas: 5, scale_rules: ['assess-queue'] },
    'acp-remediate': { min_replicas: 5, max_replicas: 10, current_replicas: 6, scale_rules: ['remediation-queue'] },
  },
  drift: [],
  drift_evaluated: false,
  azure_configured: true,
  holidays: [],
  attribution: {},
}

async function mount(data = PROPOSED) {
  snapshot.current = data
  const host = document.createElement('div')
  document.body.appendChild(host)
  await act(async () => { createRoot(host).render(<CapacitySchedule />) })
  await act(async () => { await Promise.resolve() })
  return host
}

beforeEach(() => { document.body.innerHTML = ''; snapshot.calls = 0 })

describe('Settings → Scheduling shows a proposal, not a live schedule', () => {
  it('says the schedule is not in force', async () => {
    const c = await mount()
    expect(c.textContent).toContain('Proposed schedule — not in force')
    expect(c.textContent).toMatch(/Nothing has applied this schedule/)
  })

  it('names the mode instead once a schedule is applied', async () => {
    const c = await mount({ ...PROPOSED, applied: true, enabled: true,
                            effective_mode: 'business_hours',
                            next_transition_at: '2026-09-08T03:00:00+00:00',
                            next_transition_to: 'off_hours' })
    expect(c.textContent).toContain('Business hours')
    expect(c.textContent).not.toContain('Proposed schedule — not in force')
    expect(c.textContent).toMatch(/Next transition to Off hours/)
    expect(c.textContent).toMatch(/Next transition[^.]+\([^)]+\)/)
  })

  it('reports a disabled applied schedule as having no scheduled transition, not a fabricated one', async () => {
    const c = await mount({ ...PROPOSED, applied: true })
    expect(c.textContent).toMatch(/Next transition not scheduled/)
  })
})

describe('instant timestamps name the viewer timezone', () => {
  it('labels reconciliation and override instants instead of relying on locale implicitly', async () => {
    const c = await mount({ ...PROPOSED, applied: true, enabled: true,
      reconciliation: { state: 'applied', completed_at: '2026-09-07T16:00:00Z' },
      override: { mode: 'off_hours', actor: 'owner@example.com', reason: 'maintenance', expires_at: '2026-09-08T03:00:00Z', resumes_schedule_version: 3 },
      effective_floors: { assess: 1 } })
    expect(c.textContent).toMatch(/Last checked[^.]+\([^)]+\)/)
    expect(c.textContent).toMatch(/expires[^;]+\([^)]+\)/)
  })
})

describe('the validation verdict is the point of the read-only phase', () => {
  it('renders the refusal and the arithmetic behind it', async () => {
    const c = await mount()
    expect(c.textContent).toContain('This schedule cannot be applied')
    expect(c.textContent).toContain('152')
    expect(c.textContent).toContain('150')
    expect(c.textContent).toMatch(/17 over/)
    expect(c.textContent).toMatch(/Blocks saving/)
  })

  it('says the check is against the worst mode, not the current one', async () => {
    const c = await mount()
    expect(c.textContent).toMatch(/worst mode the schedule can enter/)
  })

  it('says so plainly when a schedule does fit', async () => {
    const c = await mount({ ...PROPOSED, validation: {
      schedule_valid: true, blocked: false, findings: [],
      capacity: { ...PROPOSED.validation.capacity, deploy_connections: 118, connection_headroom: 17 },
    } })
    expect(c.textContent).toContain('This schedule fits the fleet')
    expect(c.textContent).toMatch(/leaves 17 spare/)
    expect(c.textContent).not.toContain('cannot be applied')
  })
})

describe('the service table shows intent beside what Azure runs', () => {
  it('shows every service the schedule names, with its observed range', async () => {
    const c = await mount()
    const row = c.querySelector('[data-service="assess"]')
    expect(row, 'no Assess row').toBeTruthy()
    expect(row.textContent).toContain('5')     // business-hours floor
    expect(row.textContent).toContain('10')    // maximum
    expect(row.textContent).toContain('5–5')   // what Azure actually runs
  })

  it('leaves a reading Azure did not return as a dash, never a zero', async () => {
    const c = await mount({ ...PROPOSED, observed: {
      'acp-assess': { min_replicas: null, max_replicas: null, current_replicas: null, scale_rules: [] },
    } })
    const row = c.querySelector('[data-service="assess"]')
    expect(row.textContent).toContain('—')
    expect(row.textContent).not.toContain('0–0')
  })
})

describe('scaler health distinguishes inert from healthy', () => {
  it('does not report a rule on a pinned tier as healthy', async () => {
    const c = await mount()
    expect(c.textContent).toContain('Inert — tier pinned')
    expect(c.textContent).toMatch(/cannot add a replica/)
  })

  it('reports a tier with room and no rule as missing, and one with both as healthy', async () => {
    const c = await mount()
    expect(c.textContent).toContain('No queue rule')
    expect(c.textContent).toContain('Healthy')
    expect(c.textContent).toMatch(/nothing asks it to/)
  })

  it('never reports an unreadable scaler as healthy', async () => {
    const c = await mount({ ...PROPOSED, azure_configured: false, observed: {}, scalers: {
      discovery: { app: 'acp-discovery', state: 'not_configured', rules: [] },
      assess: { app: 'acp-assess', state: 'unreadable', rules: [] },
      remediate: { app: 'acp-remediate', state: 'unreadable', rules: [] },
    } })
    expect(c.textContent).toContain('Azure not configured')
    expect(c.textContent).toContain('Unreadable')
    expect(c.textContent).not.toContain('Healthy')
  })
})

describe('drift says why it is not being evaluated', () => {
  it('does not let an empty drift list read as agreement', async () => {
    const c = await mount()
    expect(c.textContent).toMatch(/Not evaluated/)
    expect(c.textContent).not.toContain('Azure matches the schedule')
  })

  it('states agreement only once an applied schedule has actually been compared', async () => {
    const c = await mount({ ...PROPOSED, applied: true, drift_evaluated: true, drift: [] })
    expect(c.textContent).toContain('Azure matches the schedule')
  })

  it('lists each difference when an applied schedule has drifted', async () => {
    const c = await mount({ ...PROPOSED, applied: true, drift_evaluated: true,
      drift: [{ app: 'acp-assess', field: 'max_replicas', desired: 10, observed: 5 }] })
    expect(c.textContent).toMatch(/acp-assess max_replicas: schedule says 10, Azure reports 5/)
  })
})

describe('permissions and management actions', () => {
  it('gives a view-only user an explicit explanation and no mutation controls', async () => {
    const c = await mount()
    expect(c.textContent).toContain('View only')
    expect(c.textContent).toMatch(/platform administrator must make changes/i)
    expect(c.querySelectorAll('button').length).toBe(0)
    expect(c.querySelectorAll('input').length).toBe(0)
    expect(c.querySelectorAll('select').length).toBe(0)
  })

  it('puts both administrator actions above the management workspace', async () => {
    snapshot.current = PROPOSED
    const host = document.createElement('div')
    document.body.appendChild(host)
    await act(async () => { createRoot(host).render(<CapacitySchedule me={{ is_admin: true }} />) })
    await act(async () => { await Promise.resolve() })
    const actions = host.querySelector('[aria-label="Schedule actions"]')
    expect(actions.textContent).toContain('Edit schedule')
    expect(actions.textContent).toContain('Temporary override')
    expect(host.textContent).not.toContain('View only')
    expect(host.textContent).not.toContain('Edit the schedule')
    await act(async () => { [...actions.querySelectorAll('button')][0].click() })
    expect(host.textContent).toContain('Edit the schedule')
  })

  it('sends the reader to Monitor for live counts and Worker Configuration to change capacity', async () => {
    const c = await mount()
    expect(c.textContent).toMatch(/Monitor . Workers & Queue/)
    expect(c.textContent).toMatch(/Settings . Scheduling/)
  })

  it('reports a failed read as a reporting failure, not as a capacity change', async () => {
    const c = await mount(new Error('boom'))
    expect(c.textContent).toMatch(/could not be read/)
    expect(c.textContent).toMatch(/nothing has been altered/i)
  })

  it('lets a failed read be retried without reopening Settings', async () => {
    const c = await mount(new Error('slow Azure read'))
    snapshot.current = PROPOSED
    await act(async () => { c.querySelector('button').click(); await Promise.resolve() })
    expect(snapshot.calls).toBe(2)
    expect(c.textContent).toContain('Proposed schedule — not in force')
  })
})

describe('at-a-glance schedule presentation', () => {
  it('summarizes the active window and local timezone in plain language', async () => {
    const c = await mount({ ...PROPOSED, enabled: true })
    expect(c.textContent).toContain('Monday–Friday')
    expect(c.textContent).toMatch(/6:00 AM.*8:00 PM/)
    expect(c.textContent).toContain('Off-hours capacity applies at all other times')
    expect(c.textContent).toContain('local time')
  })

  it('shows the authoritative source when scheduling is disabled', async () => {
    const c = await mount()
    expect(c.textContent).toContain('Scheduling disabled')
    expect(c.textContent).toMatch(/Current Azure settings and queue demand/)
  })

  it('uses responsive service cards with understandable capacity labels', async () => {
    const c = await mount()
    expect(c.querySelectorAll('[data-service]').length).toBe(5)
    const gpu = c.querySelector('[data-service="gpu"]')
    expect(gpu.textContent).toContain('Warm · business hours')
    expect(gpu.textContent).toContain('Maximum when busy')
    expect(gpu.textContent).toMatch(/Scales to zero off hours/)
  })

  it('keeps technical details in a collapsed diagnostics disclosure', async () => {
    const c = await mount()
    const diagnostics = c.querySelector('details')
    expect(diagnostics.open).toBe(false)
    expect(diagnostics.querySelector('summary').textContent).toContain('Diagnostics')
    expect(diagnostics.textContent).toContain('QUEUE SCALERS')
    expect(diagnostics.textContent).toContain('CONFIGURATION DRIFT')
  })
})


describe('why capacity is where it is (AC 14)', () => {
  it('names each cause and does not fold "below the floor" into "scheduled"', async () => {
    const c = await mount({ ...PROPOSED, attribution: {
      web: { reason: 'scheduled', detail: 'Exactly the scheduled floor of 1.' },
      assess: { reason: 'queue', detail: '3 replica(s) above the scheduled floor of 5.' },
      remediate: { reason: 'deployment', detail: '2 replica(s) still on a previous revision.' },
      discovery: { reason: 'below_floor', detail: '1 replica(s) short of the scheduled floor of 4.' },
      gpu: { reason: 'unknown', detail: 'Azure did not answer for this app.' },
    } })
    expect(c.textContent).toContain('Scheduled floor')
    expect(c.textContent).toContain('Queue-driven')
    expect(c.textContent).toContain('Deployment in progress')
    expect(c.textContent).toContain('Below the scheduled floor')
    expect(c.textContent).toContain('Not known')
    expect(c.textContent).toMatch(/3 replica\(s\) above/)
  })

  it('renders no attribution panel when there is nothing to attribute', async () => {
    const c = await mount()
    expect(c.textContent).not.toContain('WHY CAPACITY IS WHERE IT IS')
  })
})

describe('holiday exceptions say what Azure will actually do', () => {
  it('lists the dates and states that a published policy cannot observe them', async () => {
    const c = await mount({ ...PROPOSED, holidays: ['2026-12-25', '2027-01-01'] })
    expect(c.textContent).toContain('2026-12-25')
    expect(c.textContent).toMatch(/cron scale rule cannot express an exception/)
    // The consequence in the operator's terms, not just the mechanism.
    expect(c.textContent).toMatch(/stays at the business-hours floor/)
  })

  it('renders nothing when no holidays are declared', async () => {
    const c = await mount()
    expect(c.textContent).not.toContain('HOLIDAY EXCEPTIONS')
  })
})
