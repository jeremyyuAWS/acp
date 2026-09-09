import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationWaterfallCard from './RemediationWaterfallCard.jsx'
import WaterfallCount from './WaterfallCount.jsx'
import { getFindingDispositions } from './api.js'
vi.mock('./api.js', () => ({ getFindingDispositions: vi.fn() }))
vi.mock('./useWaterfallActivity.js', () => ({ default: () => ({ view: null, error: false }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.clearAllMocks() })
const snapshot = (extra = {}) => ({ run_id: 'scan', scan_id: 'scan', batch_id: 'batch', fixes: { verified: 30 }, review: { items: 8 }, documents: { processing: 3 },
  finding_reconciliation: { exact: true, assessed: 100, resolved_verified: 30, awaiting_review: 20,
    approved_pending_verification: 5, unchanged_no_fix: 35, failed: 8, excluded: 2, superseded: 0 }, ...extra })
const activity = { view: { available: true, ai_enabled: true, stages: [
  { tier: 1, operations: 15, active: 2, settled: 13, uncertain: 0 },
  { tier: 2, operations: 5, active: 1, settled: 3, uncertain: 1 },
], spending: { cap_units: 5000000, spent_units: 1180000, held_units: 200000, available_units: 3620000, unknown_charges: 1, blocked: true } } }

it('shows durable units, costs, honest missing contribution, and accessible outcomes', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<RemediationWaterfallCard snapshot={snapshot()} activity={activity} />))
  expect(container.querySelector('.remediation-run-insights summary').textContent).toContain('Saved model history')
  expect(container.textContent).toContain('Drafts and optional reviews')
  expect(container.textContent).toContain('15 recorded operations')
  expect(container.textContent).not.toContain('15 suggestions')
  expect(container.textContent).toContain('$1.18')
  expect(container.textContent).toContain('$3.62')
  expect(container.textContent).toContain('AI step breakdown unavailable')
  expect(container.querySelectorAll('tbody tr')).toHaveLength(7)
  expect(container.querySelector('.wf-outcome-bar').children[0].style.width).toBe('30%')
  expect(container.querySelector('.wf-delta')).toBeNull()
  expect(container.querySelector('.wf-stage-flare')).toBeNull()
})
it('never builds a bar or equates changes with findings when reconciliation is incomplete', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<RemediationWaterfallCard snapshot={snapshot({ finding_reconciliation: { exact: false, assessed: 100 } })} />))
  expect(container.querySelector('.wf-outcome-bar')).toBeNull()
  expect(container.textContent).toContain('Verified changes · all origins')
  expect(container.textContent).toContain('Review items · not findings')
  expect(container.textContent).toContain('Unavailable')
})
it('opens the matching drawer and rejects a changed batch', async () => {
  const { root, container } = createTestRoot()
  const snap = snapshot({ finding_reconciliation: { ...snapshot().finding_reconciliation, resolved_verified: 1, unchanged_no_fix: 64 } })
  getFindingDispositions.mockResolvedValue({ available: true, batch_id: 'batch', items: [{ finding_id: '1', file: 'a.pdf', rule_id: '1.1.1', instance_key: 'image1' }] })
  await act(async () => root.render(<RemediationWaterfallCard snapshot={snap} />))
  await act(async () => container.querySelector('.wf-legend button').click())
  expect(document.querySelector('[role="dialog"]').textContent).toContain('a.pdf')
  await act(async () => document.querySelector('[aria-label="Close"]').click())
  getFindingDispositions.mockResolvedValue({ available: true, batch_id: 'different', items: [] })
  await act(async () => container.querySelector('.wf-legend button').click())
  expect(document.querySelector('[role="alert"]').textContent).toContain('run changed')
})
it('animates signed changes once, expires, and resets across runs and pause', async () => {
  vi.useFakeTimers()
  const { root, container } = createTestRoot()
  const render = async (value, identity = 'a', paused = false) => act(async () => root.render(<WaterfallCount value={value} identity={identity} paused={paused} />))
  await render(10)
  expect(container.querySelector('.wf-delta')).toBeNull()
  await render(15)
  expect(container.querySelector('.wf-delta').textContent).toBe('+5')
  await render(12)
  expect(container.querySelector('.wf-delta').textContent).toBe('−3')
  await act(async () => vi.advanceTimersByTime(2600))
  expect(container.querySelector('.wf-delta')).toBeNull()
  await render(20, 'b')
  expect(container.querySelector('.wf-delta')).toBeNull()
  await render(25, 'b', true)
  await render(25, 'b', false)
  expect(container.querySelector('.wf-delta')).toBeNull()
})
it('mounts in the live run and supports reduced motion with activity-gated animation', () => {
  const source = readFileSync(join(import.meta.dirname, 'RemediationOpsPanel.jsx'), 'utf8')
  expect(source).toContain('<RemediationWaterfallCard')
  const css = readFileSync(join(import.meta.dirname, 'remediation-waterfall-card.css'), 'utf8')
  expect(css).toContain('@media(prefers-reduced-motion:reduce)')
  expect(css).toContain('.wf-stage-active .wf-working i')
  expect(css).toContain('.wf-paused .wf-connector:after{animation:none!important}')
})
it('shows exact small dollar changes instead of rounding them to zero', async () => {
  const { root, container } = createTestRoot()
  const format = value => `$${(value / 1000000).toFixed(6)}`
  await act(async () => root.render(<WaterfallCount value={100} identity="budget" format={format} />))
  await act(async () => root.render(<WaterfallCount value={142} identity="budget" format={format} />))
  expect(container.textContent).toContain('$0.000142')
  expect(container.querySelector('.wf-delta').textContent).toBe('+$0.000042')
})
it('shows the recorded provider and exact model and preserves unknown costs', async () => {
  const { root, container } = createTestRoot()
  const view = { ...activity.view, models: [
    { provider: 'anthropic', model: 'recorded-model-20260908', linked_calls: 2, recorded_cost_usd: 0.000042 },
    { provider: 'openai', model: 'other-recorded-model', linked_calls: 1, recorded_cost_usd: null },
  ] }
  await act(async () => root.render(<RemediationWaterfallCard snapshot={snapshot()} activity={{ view }} />))
  expect(container.querySelector('.wf-models').textContent).toContain('anthropic · recorded-model-20260908')
  expect(container.querySelector('.wf-models').textContent).toContain('$0.000042')
  expect(container.querySelector('.wf-models').textContent).toContain('Recorded call cost: Unavailable')
  expect(container.textContent).toContain('not a model breakdown for the selected run')
})

it('places a subtle measured processing chart beside the waterfall approval status', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<RemediationWaterfallCard activity={activity}
    snapshot={snapshot({ throughput: { buckets: [0, 2, 0], documents_per_minute: 0.4 } })} />))
  const chart = container.querySelector('.wf-header-status svg')
  expect(chart.getAttribute('width')).toBe('92')
  expect(chart.getAttribute('height')).toBe('20')
  expect(chart.getAttribute('aria-label')).toContain('Document processing · last 5 minutes')
  expect(container.querySelector('.wf-tag').textContent).toContain('require your approval')
})
