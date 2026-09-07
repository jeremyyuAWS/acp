import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls = vi.hoisted(() => ({ override: 0, validation: { blocked: false, findings: [] } }))
vi.mock('./api.js', () => ({
  putCapacitySchedule: vi.fn(),
  applyCapacitySchedule: vi.fn(),
  validateCapacitySchedule: () => Promise.resolve(calls.validation),
  createCapacityOverride: () => { calls.override += 1; return Promise.resolve({}) },
  deleteCapacityOverride: vi.fn(),
}))

import CapacityScheduleEditor from './CapacityScheduleEditor.jsx'

const snap = {
  enabled: true,
  timezone: 'America/Los_Angeles',
  days: ['mon', 'tue', 'wed', 'thu', 'fri'],
  start: '06:00',
  end: '20:00',
  business_hours: { web: 1, discovery: 2, assess: 4, remediate: 4, gpu: 1 },
  off_hours: { web: 1, discovery: 1, assess: 1, remediate: 1, gpu: 0 },
  maximums: { web: 3, discovery: 4, assess: 10, remediate: 10, gpu: 1 },
  holidays: [],
  version: 7,
  applied: true,
  application_configured: true,
}

const button = (host, text) => [...host.querySelectorAll('button')]
  .find((candidate) => candidate.textContent.trim() === text)
const change = (element, value) => {
  const prototype = element.tagName === 'SELECT'
    ? HTMLSelectElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
  element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
}

async function render(props = {}) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  await act(async () => {
    createRoot(host).render(<CapacityScheduleEditor snap={snap} {...props} />)
  })
  return host
}

beforeEach(() => {
  document.body.innerHTML = ''
  calls.override = 0
  calls.validation = { blocked: false, findings: [] }
  vi.restoreAllMocks()
})

describe('scheduling control accessibility contract', () => {
  it('names the workflow, current step, timezone help, and day toggle state', async () => {
    const host = await render()
    expect(host.querySelector('section').getAttribute('aria-labelledby')).toBe('editor-title')
    expect(host.querySelector('nav[aria-label="Schedule editing steps"]')).toBeTruthy()
    expect(host.querySelector('[aria-current="step"]').textContent).toContain('When')
    expect(host.querySelector('#cap-tz').getAttribute('aria-describedby')).toBe('cap-tz-help')
    expect(host.querySelector('button[aria-label="Monday"]').getAttribute('aria-pressed')).toBe('true')
  })

  it('exposes invalid capacity at the affected input and reports validation findings', async () => {
    calls.validation = { blocked: true, findings: [{ detail: 'Needs more capacity.' }] }
    const host = await render()
    await act(async () => button(host, 'Continue').click())
    change(host.querySelector('#cap-business_hours-web'), '9')
    expect(host.querySelector('#cap-business_hours-web').getAttribute('aria-invalid')).toBe('true')
    expect(host.querySelector('[role="alert"]').textContent).toContain('Warm capacity')
    change(host.querySelector('#cap-business_hours-web'), '1')
    await act(async () => button(host, 'Continue').click())
    await act(async () => button(host, 'Check schedule').click())
    expect(host.querySelector('[role="status"]').textContent).toContain('Needs more capacity.')
  })

  it('bounds custom override fields and requires confirmation before mutation', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const host = await render({ initialView: 'override' })
    change(host.querySelector('#ov-mode'), 'custom')
    expect(host.querySelector('#ov-assess').getAttribute('max')).toBe('10')
    change(host.querySelector('#ov-reason'), 'test capacity')
    await act(async () => button(host, 'Apply override').click())
    expect(confirm).toHaveBeenCalled()
    expect(calls.override).toBe(0)
  })

  it('exposes an inline dialog, moves focus into it, and closes it with Escape', async () => {
    const onClose = vi.fn()
    const host = await render({ onClose })
    const dialog = host.querySelector('[role="dialog"]')
    expect(dialog.getAttribute('aria-labelledby')).toBe('editor-title')
    expect(document.activeElement).toBe(dialog)
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('connects custom override validation to its fields and marks the reason required', async () => {
    const host = await render({ initialView: 'override' })
    change(host.querySelector('#ov-mode'), 'custom')
    change(host.querySelector('#ov-assess'), '11')
    expect(host.querySelector('#ov-assess').getAttribute('aria-invalid')).toBe('true')
    expect(host.querySelector('#ov-assess').getAttribute('aria-describedby')).toBe('override-capacity-error')
    expect(host.querySelector('#override-capacity-error').getAttribute('role')).toBe('alert')
    expect(host.querySelector('#ov-reason').getAttribute('aria-required')).toBe('true')
  })
})
