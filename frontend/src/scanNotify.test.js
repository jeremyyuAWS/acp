// "Notify me when complete" (slice 3c). The load-bearing property is that it is a SAFE no-op in every
// environment where notifications are unavailable or denied — a completing scan must never fail because
// a notification could not be posted — and that it only ever fires when the user actually granted it.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { notificationsSupported, notifyPermission, armNotifyOnComplete, notifyScanComplete, notifyScanFailed } from './scanNotify.js'

function mockNotification({ permission = 'default', request = 'granted' } = {}) {
  const instances = []
  const N = vi.fn(function N(title, opts) { instances.push({ title, opts }) })
  N.permission = permission
  N.requestPermission = vi.fn(async () => request)
  window.Notification = N
  return { N, instances }
}

beforeEach(() => { delete window.Notification })   // deterministic: start unsupported every test
afterEach(() => { delete window.Notification })

describe('scanNotify', () => {
  it('reports support and the current permission', () => {
    expect(notificationsSupported()).toBe(false)
    expect(notifyPermission()).toBe('unsupported')
    mockNotification({ permission: 'granted' })
    expect(notificationsSupported()).toBe(true)
    expect(notifyPermission()).toBe('granted')
  })

  it('arms when granted, refuses when denied, and asks exactly once when default', async () => {
    mockNotification({ permission: 'granted' })
    expect(await armNotifyOnComplete()).toBe(true)

    mockNotification({ permission: 'denied' })
    expect(await armNotifyOnComplete()).toBe(false)

    const { N } = mockNotification({ permission: 'default', request: 'granted' })
    expect(await armNotifyOnComplete()).toBe(true)
    expect(N.requestPermission).toHaveBeenCalledTimes(1)

    mockNotification({ permission: 'default', request: 'denied' })
    expect(await armNotifyOnComplete()).toBe(false)
  })

  it('fires a completion notification only when granted, with the outcome in the body', () => {
    mockNotification({ permission: 'default' })
    expect(notifyScanComplete({ assessed: 1, total: 2 })).toBe(false)     // not granted → nothing

    const { instances } = mockNotification({ permission: 'granted' })
    expect(notifyScanComplete({ assessed: 145, total: 250, review: 23 })).toBe(true)
    expect(instances).toHaveLength(1)
    expect(instances[0].opts.body).toMatch(/145 of 250 assessed · 23 need review/)
    expect(instances[0].opts.tag).toBe('acp-scan-complete')              // collapses repeats
  })

  it('drops the review clause when there is nothing to review', () => {
    const { instances } = mockNotification({ permission: 'granted' })
    notifyScanComplete({ assessed: 40, total: 40, review: 0 })
    expect(instances[0].opts.body).toBe('40 of 40 assessed')
  })

  it('is a safe no-op when Notification is unavailable', () => {
    expect(notifyScanComplete({ assessed: 1, total: 1 })).toBe(false)     // no window.Notification
    // Even a throwing constructor must not propagate.
    window.Notification = Object.assign(vi.fn(() => { throw new Error('blocked') }), { permission: 'granted' })
    expect(notifyScanComplete({ assessed: 1, total: 1 })).toBe(false)
  })

  // Found live 2026-08-29 auditing the Discover card PRD's notification list: only "completed"
  // ever fired. Failure is the outcome a returning user is most likely to otherwise miss.
  it('fires a failure notification only when granted, with the reason in the body', () => {
    mockNotification({ permission: 'default' })
    expect(notifyScanFailed('Google Drive rate limit')).toBe(false)   // not granted → nothing

    const { instances } = mockNotification({ permission: 'granted' })
    expect(notifyScanFailed('Google Drive rate limit')).toBe(true)
    expect(instances).toHaveLength(1)
    expect(instances[0].title).toBe('ACP scan failed')
    expect(instances[0].opts.body).toBe('Google Drive rate limit')
  })

  it('uses the same tag as the completion notice — a run has exactly one outcome notification', () => {
    const { instances } = mockNotification({ permission: 'granted' })
    notifyScanFailed('some reason')
    expect(instances[0].opts.tag).toBe('acp-scan-complete')
  })

  it('falls back to a generic reason when none is given', () => {
    const { instances } = mockNotification({ permission: 'granted' })
    notifyScanFailed(undefined)
    expect(instances[0].opts.body).toMatch(/could not finish/i)
  })

  it('is a safe no-op for a failure notification when Notification is unavailable', () => {
    expect(notifyScanFailed('reason')).toBe(false)
    window.Notification = Object.assign(vi.fn(() => { throw new Error('blocked') }), { permission: 'granted' })
    expect(notifyScanFailed('reason')).toBe(false)
  })
})
