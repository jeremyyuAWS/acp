import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const calls = vi.hoisted(() => ({ saved: [] }))
vi.mock('./api.js', () => ({
  putCapacitySchedule: (body) => { calls.saved.push(body); return Promise.resolve({ version: 2 }) },
  validateCapacitySchedule: () => Promise.resolve({ blocked: false, findings: [] }),
  applyCapacitySchedule: () => Promise.resolve({}),
  createCapacityOverride: () => Promise.resolve({}),
  deleteCapacityOverride: () => Promise.resolve({}),
}))
import CapacityScheduleEditor from './CapacityScheduleEditor.jsx'

const snap = { enabled: true, timezone: 'America/Los_Angeles', days: ['mon', 'tue', 'wed', 'thu', 'fri'], start: '06:00', end: '20:00', business_hours: { web: 1 }, off_hours: { web: 0 }, maximums: { web: 2 }, holidays: [], version: 1, applied: true }
const button = (host, text) => [...host.querySelectorAll('button')].find((node) => node.textContent.trim() === text)
const setValue = (el, value) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) }
async function mount(snapshot = snap) { const host = document.createElement('div'); document.body.appendChild(host); await act(async () => createRoot(host).render(<CapacityScheduleEditor snap={snapshot} />)); return host }

beforeEach(() => { document.body.innerHTML = ''; calls.saved = [] })

describe('capacity schedule timezone controls', () => {
  it('distinguishes the browser timezone from the schedule timezone and switches in one click', async () => {
    const local = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    const scheduleZone = local === 'America/Los_Angeles' ? 'Europe/Paris' : 'America/Los_Angeles'
    const host = await mount({ ...snap, timezone: scheduleZone })
    expect(host.textContent).toContain(`Your timezone: ${local}`)
    expect(host.querySelector('#cap-tz').value).toBe(scheduleZone)
    await act(async () => button(host, 'Use my timezone').click())
    expect(host.querySelector('#cap-tz').value).toBe(local)
    expect(button(host, 'Use my timezone')).toBeFalsy()
  })

  it('accepts IANA choices, rejects invalid zones, and blocks progress until corrected', async () => {
    const host = await mount()
    expect([...host.querySelectorAll('#timezones option')].some((option) => option.value === 'Asia/Tokyo')).toBe(true)
    setValue(host.querySelector('#cap-tz'), 'Local Office Time')
    expect(host.querySelector('#cap-tz').getAttribute('aria-invalid')).toBe('true')
    expect(host.textContent).toContain('Choose a valid IANA timezone')
    await act(async () => button(host, 'Continue').click())
    await act(async () => button(host, 'Continue').click())
    expect(button(host, 'Save draft').disabled).toBe(true)
  })

  it('keeps schedule hours as wall-clock values and explains DST behavior', async () => {
    const host = await mount({ ...snap, timezone: 'Asia/Tokyo', start: '06:15', end: '20:45' })
    expect(host.textContent).toMatch(/6:15\s*AM–8:45\s*PM in Asia\/Tokyo/)
    expect(host.textContent).toContain('Times stay at the wall-clock hours entered')
    expect(host.textContent).toContain('Daylight-saving transitions follow that timezone automatically')
  })
})
