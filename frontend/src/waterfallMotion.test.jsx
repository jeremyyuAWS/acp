import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { waterfallMotion } from './waterfallMotion.js'
import RemediationWaterfallCard from './RemediationWaterfallCard.jsx'
vi.mock('./api.js', () => ({ getFindingDispositions: vi.fn() }))
vi.mock('./useWaterfallActivity.js', () => ({ default: () => ({ view: null, error: false }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const now = Date.parse('2026-09-09T00:00:00Z')
const at = offset => new Date(now + offset).toISOString()
const snapshot = extra => ({ scan_id: 'scan', run_id: 'scan', batch_id: 'batch', state: 'running', terminal: false,
  generated_at: at(0), progress: { lease_healthy: true }, documents: { processing: 3 }, fixes: { verified: 5 }, ...extra })
const view = extra => ({ available: true, ai_enabled: true, generated_at: at(0), stages: [{ tier: 1, active: 2 }, { tier: 2, active: 1 }], ...extra })
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.restoreAllMocks() })
it('chooses just one confirmed AI stage; selection can move its highlight', () => {
  expect(waterfallMotion(snapshot(), view(), { now })).toEqual({ documents: 3, stage: 'first' })
  expect(waterfallMotion(snapshot(), view(), { now, selected: 'next' }).stage).toBe('next')
})
it.each([
  { terminal: true }, { state: 'stalled' }, { state: 'cancelled' }, { generated_at: at(-61_000) },
  { generated_at: null }, { progress: { lease_healthy: false } }, { integrity: { affected: ['documents'] } },
])('stops motion for unconfirmed or inactive run %j', extra => {
  expect(waterfallMotion(snapshot(extra), view(), { now })).toEqual({ documents: 0, stage: null })
})
it('shows genuine background work while human attention is also needed', () => {
  expect(waterfallMotion(snapshot({ state: 'needs_attention', also: ['running'] }), view(), { now }).stage).toBe('first')
})
it.each([{ ai_enabled: false }, { available: false }, { generated_at: at(-61_000) },
  { stages: [{ tier: 1, reserved: 3, uncertain: 2, active: 0 }] }])('never animates disabled, stale, reserved or uncertain AI %j', extra => {
  expect(waterfallMotion(snapshot(), view(extra), { now }).stage).toBeNull()
})
it('does not turn aggregate applying/rechecking status into stage activity', () => {
  expect(waterfallMotion(snapshot({ phases: [{ key: 'applying', status: 'active' }, { key: 'rechecking', status: 'active' }] }), view({ ai_enabled: false }), { now }).stage).toBeNull()
})
it('only highlights verification with an explicit current leased attempt', () => {
  const attempt = { phase: 're-verifying corrected copy', lease_valid: true, lease_expires_at: at(30_000) }
  expect(waterfallMotion(snapshot({ active_attempts: [attempt] }), null, { now }).stage).toBe('verify')
  expect(waterfallMotion(snapshot({ active_attempts: [{ ...attempt, lease_expires_at: at(-1) }] }), null, { now }).stage).toBeNull()
})
it('pauses all motion and suppresses AI motion after a failed refresh', () => {
  expect(waterfallMotion(snapshot(), view(), { now, paused: true })).toEqual({ documents: 0, stage: null })
  expect(waterfallMotion(snapshot(), view(), { now, error: true }).stage).toBeNull()
})
it('renders one active stage, pauses locally, and expires without another server update', async () => {
  vi.useFakeTimers(); vi.setSystemTime(now)
  const { root, container } = createTestRoot()
  await act(async () => root.render(<RemediationWaterfallCard snapshot={snapshot()} activity={{ view: view() }} />))
  expect(container.querySelectorAll('.wf-stage-active')).toHaveLength(1)
  expect(container.textContent).toContain('3 documents processing')
  expect(container.querySelector('.wf-delta')).toBeNull()
  const pause = [...container.querySelectorAll('button')].find(button => button.textContent === 'Pause animation')
  await act(async () => pause.click())
  expect(container.querySelector('.wf-stage-active')).toBeNull()
  await act(async () => pause.click())
  expect(container.querySelectorAll('.wf-stage-active')).toHaveLength(1)
  await act(async () => vi.advanceTimersByTime(65_000))
  expect(container.querySelector('.wf-stage-active')).toBeNull()
  expect(container.querySelector('.wf-processing-dot')).toBeNull()
})
it('shows signed deltas for actual results, and stops when the document is hidden', async () => {
  vi.useFakeTimers(); vi.setSystemTime(now)
  const { root, container } = createTestRoot()
  const render = verified => act(async () => root.render(<RemediationWaterfallCard snapshot={snapshot({ fixes: { verified } })} activity={{ view: view() }} />))
  await render(5); await render(8)
  expect(container.querySelector('.wf-delta').textContent).toBe('+3')
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  expect(container.querySelector('.wf-stage-active')).toBeNull()
  expect(container.querySelector('.wf-delta')).toBeNull()
})
it('titles stages with actual recorded models and keeps activity independent of their names', async () => {
  vi.useFakeTimers(); vi.setSystemTime(now)
  const { root, container } = createTestRoot()
  await act(async () => root.render(<RemediationWaterfallCard snapshot={snapshot()} activity={{ view: view({ stages: [
    { tier: 1, active: 1, operations: 2, models: [{ provider: 'openai', model: 'recorded-model' }] },
    { tier: 2, active: 0, operations: 0, models: [] },
  ] }) }} />))
  expect(container.textContent).toContain('02 · recorded-model')
  expect(container.textContent).toContain('First attempt · openai')
  expect(container.textContent).toContain('03 · Not used yet')
  expect(container.querySelector('.wf-working').textContent).toContain('Request dispatched')
})
