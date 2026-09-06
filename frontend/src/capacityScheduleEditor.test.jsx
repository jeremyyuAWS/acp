/**
 * The administrator half of Settings → Scheduling, at the DOM level.
 *
 * What these hold is the three things the UI has to get right because the API cannot do them for
 * it: the version has to TRAVEL with the edit, a reason has to be present before Save is
 * reachable, and a 409 has to be rendered as "someone else saved" rather than as a generic
 * failure. Each of those is invisible when wrong — the save appears to work.
 *
 * And the one thing the UI must not do: render optimistically. Warm capacity is real money and a
 * real restart, and a floor that appears to save and quietly reverts is indistinguishable from
 * one that saved.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const calls = vi.hoisted(() => ({ put: [], validate: [], override: [], del: 0,
                                  putResult: null, validateResult: null, overrideResult: null }))
vi.mock('./api.js', () => ({
  getCapacitySchedule: () => Promise.resolve(calls.snapshot),
  // `putFails` rather than a pre-built rejected promise: assigning `Promise.reject(...)` to a
  // variable rejects it immediately, before any test awaits it, which vitest reports as an
  // unhandled rejection even though the test itself passes.
  putCapacitySchedule: (body) => { calls.put.push(body); return calls.putFails
    ? Promise.reject(new Error('boom'))
    : Promise.resolve(calls.putResult ?? { ...body, version: body.version + 1 }) },
  validateCapacitySchedule: (body) => { calls.validate.push(body); return Promise.resolve(calls.validateResult ?? { blocked: false, findings: [], capacity: null }) },
  createCapacityOverride: (body) => { calls.override.push(body); return Promise.resolve(calls.overrideResult ?? { override: body }) },
  deleteCapacityOverride: () => { calls.del += 1; return Promise.resolve({ cleared: true }) },
}))

import CapacitySchedule from './CapacitySchedule.jsx'

const SNAP = {
  enabled: true, timezone: 'America/Los_Angeles',
  days: ['mon', 'tue', 'wed', 'thu', 'fri'], start: '06:00', end: '20:00',
  business_hours: { web: 1, discovery: 2, assess: 4, remediate: 4, gpu: 1 },
  off_hours: { web: 1, discovery: 1, assess: 1, remediate: 1, gpu: 0 },
  maximums: { web: 3, discovery: 4, assess: 10, remediate: 10, gpu: 1 },
  effective_mode: 'business_hours', effective_floors: {}, next_transition_at: null,
  next_transition_to: null, version: 7, applied: true, override: null,
  validation: { blocked: false, findings: [], capacity: null },
  scalers: {}, observed: {}, drift: [], drift_evaluated: true, azure_configured: true,
}

const ADMIN = { is_admin: true }

async function mount({ me = ADMIN, snapshot = SNAP } = {}) {
  calls.snapshot = snapshot
  const host = document.createElement('div')
  document.body.appendChild(host)
  await act(async () => { createRoot(host).render(<CapacitySchedule me={me} />) })
  await act(async () => { await Promise.resolve() })
  return host
}

const button = (c, text) => [...c.querySelectorAll('button')].find((b) => b.textContent.trim() === text)
const field = (c, id) => c.querySelector(`#${id}`)

function type(el, value) {
  const proto = el.type === 'number' || el.type === 'time' || el.tagName === 'SELECT'
    ? (el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype)
    : window.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
  el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
}

beforeEach(() => {
  document.body.innerHTML = ''
  calls.put = []; calls.validate = []; calls.override = []; calls.del = 0
  calls.putResult = null; calls.validateResult = null; calls.overrideResult = null
  calls.putFails = false
})

describe('the editor is for administrators only', () => {
  it('renders no editor and no controls for a view-only user', async () => {
    const c = await mount({ me: { is_admin: false } })
    expect(c.textContent).not.toContain('Edit the schedule')
    expect(c.querySelectorAll('button').length).toBe(0)
    expect(c.querySelectorAll('input').length).toBe(0)
    expect(c.textContent).toMatch(/view-only access/)
  })

  it('renders the editor for an admin', async () => {
    const c = await mount()
    expect(c.textContent).toContain('Edit the schedule')
    expect(button(c, 'Save schedule')).toBeTruthy()
  })
})

describe('a save carries the version it was opened on', () => {
  it('sends the snapshot version, not a re-read one', async () => {
    const c = await mount()
    type(field(c, 'cap-reason'), 'warm earlier for the EU team')
    await act(async () => { button(c, 'Save schedule').click() })
    expect(calls.put).toHaveLength(1)
    expect(calls.put[0].version).toBe(7)
    expect(calls.put[0].reason).toBe('warm earlier for the EU team')
  })

  it('sends the edited fields', async () => {
    const c = await mount()
    type(field(c, 'cap-start'), '07:30')
    type(field(c, 'cap-reason'), 'later start')
    await act(async () => { button(c, 'Save schedule').click() })
    expect(calls.put[0].start).toBe('07:30')
  })

  it('renders a concurrent edit as someone else saving, with both numbers', async () => {
    calls.putResult = { detail: { your_version: 7, current_version: 9 } }
    const c = await mount()
    type(field(c, 'cap-reason'), 'my change')
    await act(async () => { button(c, 'Save schedule').click() })
    expect(c.textContent).toMatch(/Someone else saved while you were editing/)
    expect(c.textContent).toContain('7')
    expect(c.textContent).toContain('9')
    expect(c.textContent).toMatch(/Reload/)
  })

  it('shows the findings when the server refuses the shape', async () => {
    calls.putResult = { detail: { blocked: true, findings: [
      { code: 'over_connection_budget', blocking: true, detail: 'Over by 17.' }] } }
    const c = await mount()
    type(field(c, 'cap-reason'), 'the PRD table')
    await act(async () => { button(c, 'Save schedule').click() })
    expect(c.textContent).toContain('Over by 17.')
    expect(c.textContent).toMatch(/cannot be applied/)
  })
})

describe('a reason is required before an edit can be saved', () => {
  it('disables Save until a reason is typed', async () => {
    const c = await mount()
    expect(button(c, 'Save schedule').disabled).toBe(true)
    expect(c.textContent).toMatch(/A reason is required before saving/)
    type(field(c, 'cap-reason'), 'because')
    expect(button(c, 'Save schedule').disabled).toBe(false)
  })

  it('does not accept whitespace as a reason', async () => {
    const c = await mount()
    type(field(c, 'cap-reason'), '    ')
    expect(button(c, 'Save schedule').disabled).toBe(true)
  })
})

describe('checking a schedule is offered before saving it', () => {
  it('sends the draft and renders the verdict', async () => {
    calls.validateResult = { blocked: true, findings: [{ code: 'x', blocking: true, detail: 'Over by 9.' }],
                             capacity: { deploy_connections: 159, reserve: 15, server_max_connections: 150 } }
    const c = await mount()
    await act(async () => { button(c, 'Check this schedule').click() })
    expect(calls.validate).toHaveLength(1)
    expect(calls.validate[0].timezone).toBe('America/Los_Angeles')
    expect(c.textContent).toContain('Over by 9.')
    expect(c.textContent).toContain('159')
  })

  it('does not require a check before saving — the server validates again', async () => {
    // A client-side gate that could be bypassed would be the more dangerous half of a two-part
    // check. The server refuses regardless; the client only makes the refusal visible earlier.
    const c = await mount()
    type(field(c, 'cap-reason'), 'no check first')
    expect(button(c, 'Save schedule').disabled).toBe(false)
    await act(async () => { button(c, 'Save schedule').click() })
    expect(calls.put).toHaveLength(1)
    expect(calls.validate).toHaveLength(0)
  })
})

describe('overrides', () => {
  it('requires a reason before an override can be applied', async () => {
    const c = await mount()
    expect(button(c, 'Apply override').disabled).toBe(true)
    type(field(c, 'ov-reason'), 'large batch landing')
    expect(button(c, 'Apply override').disabled).toBe(false)
  })

  it('sends the mode, duration and reason', async () => {
    const c = await mount()
    type(field(c, 'ov-reason'), 'large batch landing')
    type(field(c, 'ov-duration'), '4h')
    await act(async () => { button(c, 'Apply override').click() })
    expect(calls.override[0]).toMatchObject({ mode: 'business_hours', duration: '4h',
                                              reason: 'large batch landing' })
  })

  it('shows an active override with who set it, why, and that it expires by itself', async () => {
    const c = await mount({ snapshot: { ...SNAP, override: {
      mode: 'business_hours', actor: 'owner@example.com', reason: 'large batch landing',
      expires_at: '2026-09-08T03:00:00+00:00', resumes_schedule_version: 7 } } })
    expect(c.textContent).toContain('owner@example.com')
    expect(c.textContent).toContain('large batch landing')
    expect(c.textContent).toMatch(/resumes automatically/)
    expect(c.textContent).toMatch(/cannot become permanent/)
    expect(button(c, 'Apply override')).toBeFalsy()
  })

  it('cancels an active override', async () => {
    const c = await mount({ snapshot: { ...SNAP, override: {
      mode: 'off_hours', actor: 'a', reason: 'r',
      expires_at: '2026-09-08T03:00:00+00:00', resumes_schedule_version: 7 } } })
    await act(async () => { button(c, 'Cancel the override now').click() })
    expect(calls.del).toBe(1)
  })
})

describe('nothing is rendered optimistically', () => {
  it('does not change the displayed schedule until the server has answered', async () => {
    const c = await mount()
    type(field(c, 'cap-start'), '09:15')
    // The read-only summary above the editor still shows what the SERVER last returned. An
    // optimistic floor that reverts is indistinguishable from one that saved.
    const summary = c.querySelector('.panel')
    expect(summary.textContent).not.toContain('09:15')
  })

  it('reports a failed save as having changed nothing', async () => {
    calls.putFails = true
    const c = await mount()
    type(field(c, 'cap-reason'), 'r')
    await act(async () => { button(c, 'Save schedule').click() })
    await act(async () => { await Promise.resolve() })
    expect(c.textContent).toMatch(/Nothing was changed|could not be saved/)
  })
})
