import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
afterEach(unmountAll)

const calls = vi.hoisted(() => ({ put: [], apply: [], validate: [], override: [], del: 0, get: 0, putResult: null }))
vi.mock('./api.js', () => ({
  getCapacitySchedule: () => { calls.get += 1; return Promise.resolve(calls.snapshot) },
  putCapacitySchedule: (body) => { calls.put.push(body); if (calls.putError) return Promise.reject(calls.putError); return calls.putFails ? Promise.reject(new Error('no')) : Promise.resolve(calls.putResult ?? { version: 8 }) },
  applyCapacitySchedule: (body) => { calls.apply.push(body); return Promise.resolve({ application: { state: 'applied' } }) },
  validateCapacitySchedule: (body) => { calls.validate.push(body); return Promise.resolve(calls.validation ?? { blocked: false, findings: [] }) },
  createCapacityOverride: (body) => { calls.override.push(body); return Promise.resolve({ override: body }) },
  deleteCapacityOverride: () => { calls.del += 1; return Promise.resolve({ cleared: true }) },
}))
import CapacitySchedule from './CapacitySchedule.jsx'

const SNAP = { enabled: true, timezone: 'America/Los_Angeles', days: ['mon', 'tue', 'wed', 'thu', 'fri'], start: '06:00', end: '20:00', business_hours: { web: 1, discovery: 2, assess: 4, remediate: 4, gpu: 1 }, off_hours: { web: 1, discovery: 1, assess: 1, remediate: 1, gpu: 0 }, maximums: { web: 3, discovery: 4, assess: 10, remediate: 10, gpu: 1 }, effective_mode: 'business_hours', effective_floors: {}, version: 7, applied: true, application_configured: true, override: null, reconciliation: { state: 'applied', completed_at: '2026-09-07T16:00:00Z', failures: 0 }, validation: { blocked: false, findings: [] }, scalers: {}, observed: {}, drift: [], drift_evaluated: true, azure_configured: true, holidays: ['2026-12-25'], attribution: {} }
const button = (c, text) => [...c.querySelectorAll('button')].find((b) => b.textContent.trim() === text)
const setValue = (el, value) => { const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })) }
async function mount({ admin = true, snapshot = SNAP } = {}) { calls.snapshot = snapshot; const { container: host, root } = createTestRoot(); await act(async () => { root.render(<CapacitySchedule me={{ is_admin: admin }} />) }); await act(async () => { await Promise.resolve() }); return host }
async function open(c, name = 'Edit schedule') { await act(async () => { button(c, name).click() }) }
async function review(c) { await act(async () => { button(c, 'Continue').click() }); await act(async () => { button(c, 'Continue').click() }) }

beforeEach(() => { document.body.innerHTML = ''; calls.put = []; calls.apply = []; calls.validate = []; calls.override = []; calls.del = 0; calls.get = 0; calls.putResult = null; calls.putFails = false; calls.putError = null; calls.validation = null; vi.restoreAllMocks(); vi.spyOn(window, 'confirm').mockReturnValue(true) })

describe('guided schedule management', () => {
  it('keeps mutation controls away from view-only users', async () => { const c = await mount({ admin: false }); expect(button(c, 'Edit schedule')).toBeFalsy(); expect(c.textContent).toMatch(/View only/i) })
  it('guides administrators through When, Capacity, and Review', async () => { const c = await mount(); await open(c); expect(c.textContent).toContain('When should warm capacity run?'); expect(c.querySelector('[aria-current="step"]').textContent).toContain('When'); await act(async () => button(c, 'Continue').click()); expect(c.textContent).toContain('Choose capacity for each service'); await act(async () => button(c, 'Continue').click()); expect(c.textContent).toContain('Review & apply') })
  it('offers a labeled searchable timezone and accessible day toggles', async () => { const c = await mount(); await open(c); expect(c.querySelector('#cap-tz').getAttribute('list')).toBe('timezones'); expect(c.querySelector('button[aria-label="Monday"]').getAttribute('aria-pressed')).toBe('true'); expect(c.textContent).toMatch(/Monday–Friday/) })
  it('adds and removes holiday date chips', async () => { const c = await mount(); await open(c); expect(button(c, 'Remove 2026-12-25') || c.querySelector('[aria-label="Remove 2026-12-25"]')).toBeTruthy(); setValue(c.querySelector('#cap-holidays'), '2027-01-01'); await act(async () => button(c, 'Add date').click()); expect(c.textContent).toContain('2027-01-01'); await act(async () => c.querySelector('[aria-label="Remove 2027-01-01"]').click()); expect(c.querySelector('[aria-label="Remove 2027-01-01"]')).toBeFalsy() })
  it('shows numeric relationship errors beside the service', async () => { const c = await mount(); await open(c); await act(async () => button(c, 'Continue').click()); setValue(c.querySelector('#cap-business_hours-web'), '9'); expect(c.textContent).toContain('Warm capacity cannot exceed the maximum'); expect(c.querySelector('#cap-business_hours-web').getAttribute('aria-invalid')).toBe('true') })
  it('saves the reviewed draft with the original version and reason', async () => { const c = await mount(); await open(c); setValue(c.querySelector('#cap-start'), '07:30'); await review(c); expect(button(c, 'Save draft').disabled).toBe(true); setValue(c.querySelector('#cap-reason'), 'support the morning team'); await act(async () => button(c, 'Save draft').click()); expect(calls.put[0]).toMatchObject({ start: '07:30', version: 7, reason: 'support the morning team' }) })
  it('keeps a durable saved confirmation after the editor closes and data refreshes', async () => { const c = await mount(); await open(c); await review(c); setValue(c.querySelector('#cap-reason'), 'record reviewed intent'); await act(async () => { button(c, 'Save draft').click(); await Promise.resolve() }); const status = c.querySelector('[data-testid="schedule-confirmation"]'); expect(status.textContent).toContain('Schedule version 8 saved as a draft'); expect(c.textContent).not.toContain('Edit the schedule'); await act(async () => { await Promise.resolve() }); expect(c.querySelector('[data-testid="schedule-confirmation"]')).toBe(status) })
  it('renders validation findings in review', async () => { calls.validation = { blocked: true, findings: [{ detail: 'Needs 17 more database connections.' }] }; const c = await mount(); await open(c); await review(c); await act(async () => button(c, 'Check schedule').click()); expect(c.textContent).toContain('Needs 17 more database connections.'); expect(c.textContent).toContain('cannot be applied') })
  it('protects a dirty editor from accidental close', async () => { vi.spyOn(window, 'confirm').mockReturnValue(false); const c = await mount(); await open(c); setValue(c.querySelector('#cap-start'), '07:30'); await act(async () => button(c, 'Close').click()); expect(window.confirm).toHaveBeenCalled(); expect(c.textContent).toContain('Edit the schedule') })
  it('applies a saved schedule only after a successful check', async () => { const c = await mount({ snapshot: { ...SNAP, applied: false, application_configured: true } }); await open(c); await review(c); setValue(c.querySelector('#cap-reason'), 'publish approved hours'); expect(button(c, 'Apply saved schedule').disabled).toBe(true); await act(async () => button(c, 'Check schedule').click()); await act(async () => button(c, 'Apply saved schedule').click()); expect(calls.apply[0]).toEqual({ version: 7, reason: 'publish approved hours' }) })
  it('explains when Azure application is unavailable instead of offering a failing action', async () => { const c = await mount({ snapshot: { ...SNAP, applied: false, application_configured: false } }); await open(c); await review(c); expect(button(c, 'Apply saved schedule')).toBeFalsy(); expect(c.textContent).toMatch(/Azure application is not configured/) })
  it('explains and preserves concurrent edits', async () => { calls.putResult = { detail: { your_version: 7, current_version: 9 } }; const c = await mount(); await open(c); await review(c); setValue(c.querySelector('#cap-reason'), 'my edit'); await act(async () => button(c, 'Save draft').click()); expect(c.textContent).toMatch(/Someone else saved/); expect(c.textContent).toContain('9') })
})

describe('temporary overrides', () => {
  it('requires a reason and sends mode and duration', async () => { const c = await mount(); await open(c, 'Temporary override'); expect(button(c, 'Apply override').disabled).toBe(true); setValue(c.querySelector('#ov-duration'), '4h'); setValue(c.querySelector('#ov-reason'), 'large batch'); await act(async () => button(c, 'Apply override').click()); expect(calls.override[0]).toMatchObject({ mode: 'business_hours', duration: '4h', reason: 'large batch' }) })
  it('offers bounded per-service controls for a custom override', async () => { const c = await mount(); await open(c, 'Temporary override'); setValue(c.querySelector('#ov-mode'), 'custom'); setValue(c.querySelector('#ov-assess'), '3'); setValue(c.querySelector('#ov-reason'), 'smaller test run'); await act(async () => button(c, 'Apply override').click()); expect(calls.override[0]).toMatchObject({ mode: 'custom', reason: 'smaller test run', floors: { assess: 3 } }); expect(window.confirm).toHaveBeenCalled() })
  it('shows and ends an active override', async () => { const snapshot = { ...SNAP, override: { mode: 'off_hours', actor: 'owner@example.com', reason: 'maintenance', expires_at: '2026-09-08T03:00:00Z', resumes_schedule_version: 7 } }; const c = await mount({ snapshot }); await open(c, 'Temporary override'); expect(c.textContent).toContain('owner@example.com'); expect(c.textContent).toContain('resumes automatically'); await act(async () => button(c, 'End override').click()); expect(calls.del).toBe(1) })
  it('does not offer overrides that cannot reach Azure', async () => { const c = await mount({ snapshot: { ...SNAP, applied: false, application_configured: false } }); expect(button(c, 'Temporary override').disabled).toBe(true); expect(c.textContent).toMatch(/overrides are unavailable until this schedule is applied/i); expect(calls.override).toHaveLength(0) })
  it('explains reconciliation failures and offers an immediate refresh', async () => { const c = await mount({ snapshot: { ...SNAP, reconciliation: { state: 'partial', failures: 2, completed_at: '2026-09-07T16:00:00Z' } } }); expect(c.textContent).toContain('Some services did not update'); expect(c.textContent).toContain('2 failed attempts'); expect(c.querySelector('[role="status"]').getAttribute('aria-live')).toBe('polite'); await act(async () => button(c, 'Refresh status').click()); expect(calls.get).toBe(2) })
  it('separates active override floors from the unchanged weekly values', async () => { const c = await mount({ snapshot: { ...SNAP, override: { mode: 'custom', actor: 'owner@example.com', reason: 'batch', expires_at: '2026-09-08T03:00:00Z', resumes_schedule_version: 7 }, effective_floors: { web: 2, discovery: 3, assess: 6, remediate: 6, gpu: 1 } } }); expect(c.querySelector('#temporary-floor-heading').textContent).toContain('ACTIVE'); expect(c.querySelector('[aria-labelledby="temporary-floor-heading"]').textContent).toContain('6 warm'); expect(c.querySelector('[data-service="assess"]').textContent).toContain('Warm · business hours4') })
})

describe('read-only policy verification', () => {
  it('shows desired, reconciler-applied, and Azure values from the snapshot', async () => { const c = await mount({ snapshot: { ...SNAP, effective_floors: { assess: 4 }, reconciliation: { ...SNAP.reconciliation, authority: 'saved_schedule', desired_key: 'schedule:7:business', applied_key: 'schedule:7:business', attempted_at: '2026-09-07T15:59:00Z' }, observed: { 'acp-assess': { min_replicas: 4, max_replicas: 10 } } } }); const row = c.querySelector('[data-verification-service="assess"]'); expect(row.textContent).toContain('Assess'); expect(row.textContent).toContain('4'); expect(row.textContent).toContain('4–10'); expect(c.textContent).toContain('Matches desired policy'); expect(c.textContent).toMatch(/Last attempt.*\([^)]+\)/) })
  it('does not claim an applied floor when reconciliation keys differ', async () => { const c = await mount({ snapshot: { ...SNAP, effective_floors: { assess: 6 }, reconciliation: { state: 'applying', desired_key: 'override:8', applied_key: 'schedule:7' } } }); expect(c.querySelector('[data-verification-service="assess"]').textContent).toContain('Not verified'); expect(c.textContent).toContain('Does not yet match desired policy') })
})


describe('server save rejections', () => {
  async function saveWithError(error) {
    calls.putError = error
    const c = await mount()
    await open(c)
    await review(c)
    setValue(c.querySelector('#cap-reason'), 'keep my draft')
    await act(async () => { button(c, 'Save draft').click(); await Promise.resolve() })
    return c
  }
  it('shows the actual rejected version conflict and preserves the draft', async () => {
    const c = await saveWithError(Object.assign(new Error('conflict'), { status: 409, detail: { your_version: 7, current_version: 9 } }))
    expect(c.textContent).toContain('current is 9')
    expect(c.querySelector('#cap-reason').value).toBe('keep my draft')
    expect(c.querySelector('[data-testid="schedule-confirmation"]')).toBeNull()
  })
  it('shows blocking capacity findings returned with HTTP 422', async () => {
    const c = await saveWithError(Object.assign(new Error('invalid'), { status: 422, detail: { blocked: true, findings: [{ blocking: true, detail: 'Reduce the maximum Assess replicas to fit database capacity.' }] } }))
    expect(c.textContent).toContain('Reduce the maximum Assess replicas')
    expect(c.querySelector('#cap-reason').value).toBe('keep my draft')
  })
  it('explains a permissions rejection', async () => {
    const c = await saveWithError(Object.assign(new Error('forbidden'), { status: 403 }))
    expect(c.textContent).toContain('permission to manage worker configuration')
  })
  it('does not claim a timed-out write changed nothing', async () => {
    const c = await saveWithError(new Error('network timeout'))
    expect(c.textContent).toContain('could not confirm')
    expect(c.textContent).not.toContain('Nothing was changed')
  })
})
