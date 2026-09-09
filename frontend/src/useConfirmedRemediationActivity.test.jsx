import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import useConfirmedRemediationActivity, { confirmedRemediationActivity } from './useConfirmedRemediationActivity.js'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const now = Date.parse('2026-09-08T12:00:00Z')
const snapshot = extra => ({ state: 'running', terminal: false, generated_at: new Date(now).toISOString(), documents: { processing: 1 }, progress: { lease_healthy: true }, integrity: { affected: [] }, ...extra })
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now) })
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.restoreAllMocks() })
it('requires fresh running state and positive processing with a healthy lease', () => {
  expect(confirmedRemediationActivity(snapshot(), now)).toBe(true)
  expect(confirmedRemediationActivity(snapshot({ state: 'needs_attention', also: ['running'] }), now)).toBe(true)
  expect(confirmedRemediationActivity(snapshot({ state: 'needs_attention' }), now)).toBe(false)
  expect(confirmedRemediationActivity(snapshot({ documents: { processing: 0, waiting: 177, review: 177 } }), now)).toBe(false)
  expect(confirmedRemediationActivity(snapshot({ progress: {} }), now)).toBe(false)
})
it('rejects terminal, paused, stale, future, missing and compromised evidence', () => {
  for (const extra of [{ terminal: true }, { state: 'paused' }, { generated_at: null }, { generated_at: new Date(now - 60_000).toISOString() }, { generated_at: new Date(now + 5001).toISOString() }, { integrity: { affected: ['documents'] } }, { integrity: { affected: ['freshness'] } }]) expect(confirmedRemediationActivity(snapshot(extra), now)).toBe(false)
  expect(confirmedRemediationActivity(null, now)).toBe(false)
})
it('accepts an explicit unexpired active attempt independently of document counts', () => {
  const base = snapshot({ documents: { processing: 0 }, progress: {}, active_attempts: [{ lease_valid: true, lease_expires_at: new Date(now + 1000).toISOString() }] })
  expect(confirmedRemediationActivity(base, now)).toBe(true)
  expect(confirmedRemediationActivity(base, now + 1000)).toBe(false)
  expect(confirmedRemediationActivity({ ...base, active_attempts: [{ lease_valid: false, lease_expires_at: new Date(now + 1000).toISOString() }] }, now)).toBe(false)
})
function Indicator({ value }) { return createElement('span', null, String(useConfirmedRemediationActivity(value))) }
async function mount(value) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Indicator, { value })))
  return container
}
it('expires a fresh snapshot without a new server update and stops its timer', async () => {
  const container = await mount(snapshot())
  expect(container.textContent).toBe('true')
  await act(async () => vi.advanceTimersByTime(60_000))
  expect(container.textContent).toBe('false')
  expect(vi.getTimerCount()).toBe(0)
})
it('expires on the exact lease deadline and suspends while the page is hidden', async () => {
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  const container = await mount(snapshot({ documents: { processing: 0 }, active_attempts: [{ lease_valid: true, lease_expires_at: new Date(now + 3200).toISOString() }] }))
  expect(container.textContent).toBe('true')
  await act(async () => { hidden.mockReturnValue(true); document.dispatchEvent(new Event('visibilitychange')) })
  expect(container.textContent).toBe('false')
  expect(vi.getTimerCount()).toBe(0)
  await act(async () => { hidden.mockReturnValue(false); document.dispatchEvent(new Event('visibilitychange')) })
  expect(container.textContent).toBe('true')
  await act(async () => vi.advanceTimersByTime(3200))
  expect(container.textContent).toBe('false')
  expect(vi.getTimerCount()).toBe(0)
})
