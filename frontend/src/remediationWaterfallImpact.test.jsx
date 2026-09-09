import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import Impact, { deriveWaterfallImpact } from './RemediationWaterfallImpact.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(() => { unmountAll(); vi.unstubAllGlobals() })
const preview = () => ({
  scan_id: 'scan-selected', policy: { rule_based: 0, ai: 1, ai_budget_usd: '25.00' },
  open: { findings: 10, files: 2 }, integrity: { complete: true, open_equals_lane_sum: true },
  findings: [
    { id: 'rules', file: 'first.pdf', origin: 'rule_based', lane: 'review', finding_count: 3 },
    { id: 'ai', file: 'first.pdf', origin: 'ai', lane: 'review', finding_count: 4 },
    { id: 'manual', file: 'second.pdf', origin: 'human', lane: 'manual', finding_count: 2 },
    { id: 'blocked', file: 'second.pdf', origin: 'ai', lane: 'blocked', finding_count: 1 },
  ],
})
async function render(data, props = {}) {
  const mounted = createTestRoot()
  await act(async () => mounted.root.render(createElement(Impact, { data, ...props })))
  return mounted
}
it('reconciles route counts with approval-required rules separate from AI eligibility', async () => {
  const data = preview(), result = deriveWaterfallImpact(data)
  expect(result.complete).toBe(true)
  expect(Object.values(result.groups).map(group => group.count)).toEqual([3, 4, 2, 1])
  const { container } = await render(data)
  expect(container.querySelector('.waterfall-impact__stack').children).toHaveLength(4)
  expect([...container.querySelectorAll('tbody td strong')].map(el => el.textContent)).toEqual(['3', '4', '2', '1'])
  expect(container.textContent).toContain('A person must approve every rule-based change')
  expect(container.textContent).toContain('planned routes, not completed fixes')
  expect(container.querySelector('caption').textContent).toBe('Selected findings by planned route')
})
it('allows keyboard focus and read-only drilldown without making requests', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
  const onInspectAI = vi.fn(), onInspectRoute = vi.fn(), data = preview()
  const { container } = await render(data, { onInspectAI, onInspectRoute })
  const buttons = [...container.querySelectorAll('button')]
  expect(buttons).toHaveLength(4)
  for (const button of buttons) {
    expect(button.type).toBe('button')
    await act(async () => { button.focus(); button.click() })
    expect(document.activeElement).toBe(button)
  }
  expect(onInspectAI).toHaveBeenCalledWith([data.findings[1]])
  expect(onInspectRoute).toHaveBeenCalledWith('rule_based', [data.findings[0]])
  expect(fetch).not.toHaveBeenCalled()
})
it.each([
  data => { data.integrity.complete = false },
  data => { data.integrity.open_equals_lane_sum = false },
  data => { data.open.findings = 11 },
  data => { data.findings[1].finding_count = null },
  data => { data.findings[1].lane = 'unknown' },
  data => { data.findings.push(data.findings[1]) },
])('does not size a chart when reconciliation is incomplete', async mutate => {
  const data = preview(); mutate(data)
  const { container } = await render(data)
  expect(container.querySelector('.waterfall-impact__stack')).toBeNull()
  expect(container.querySelector('.waterfall-impact__track')).toBeNull()
  expect(container.textContent).toContain('could not be fully reconciled')
})
it('shows unknown instead of zero when no routing evidence was returned', async () => {
  const { container } = await render({ findings: {} })
  expect([...container.querySelectorAll('tbody td strong')].map(el => el.textContent)).toEqual(Array(4).fill('Not yet known'))
})
it('updates selected scope without retaining earlier counts or details', async () => {
  const onInspectAI = vi.fn(), { root, container } = await render(preview(), { onInspectAI })
  const next = preview()
  next.open = { findings: 2, files: 1 }
  next.findings = [{ id: 'new', file: 'new.pdf', origin: 'ai', lane: 'review', finding_count: 2 }]
  await act(async () => root.render(createElement(Impact, { data: next, onInspectAI })))
  expect(container.textContent).toContain('2 unresolved findings')
  expect([...container.querySelectorAll('tbody td strong')].map(el => el.textContent)).toEqual(['0', '2', '0', '0'])
  await act(async () => container.querySelector('button').click())
  expect(onInspectAI).toHaveBeenCalledWith(next.findings)
})
it('uses the server rules-only route and describes a zero paid budget honestly', async () => {
  const data = preview(); data.policy.ai = 0; data.findings[1].lane = 'manual'
  const { root, container } = await render(data)
  expect(deriveWaterfallImpact(data).groups.ai.count).toBe(0)
  expect(container.textContent).toContain('will not ask AI for new suggestions')
  const zero = preview(); zero.policy.ai_budget_usd = '0.00'
  await act(async () => root.render(createElement(Impact, { data: zero })))
  expect(container.textContent).toContain('No paid AI requests are allowed')
})

it('counts auto-approved AI rows in the AI segment instead of dropping the chart', () => {
  // Under standing approval the backend forecasts eligible AI rows into the
  // `automatic` lane. Before this was handled they matched no branch, fell out of
  // every group, and broke the counted === total invariant that gates the chart --
  // so the panel degraded to "Not yet known" exactly when AI was most active.
  const data = preview()
  data.findings = [
    { id: 'rules', file: 'first.pdf', origin: 'rule_based', lane: 'review', finding_count: 3 },
    { id: 'ai-auto', file: 'first.pdf', origin: 'ai', lane: 'automatic', finding_count: 4 },
    { id: 'manual', file: 'second.pdf', origin: 'human', lane: 'manual', finding_count: 2 },
    { id: 'blocked', file: 'second.pdf', origin: 'ai', lane: 'blocked', finding_count: 1 },
  ]
  const { groups, complete, total } = deriveWaterfallImpact(data)
  expect(complete).toBe(true)
  expect(total).toBe(10)
  expect(groups.ai.count).toBe(4)
  expect(groups.rule_based.count).toBe(3)
  // The segments still sum to the baseline, which is the chart's whole contract.
  expect(Object.values(groups).reduce((s, g) => s + g.count, 0)).toBe(10)
})

it('still refuses to draw when a row genuinely fits no segment', () => {
  // Bite check for the test above: widening the AI branch must not make the
  // completeness gate unfalsifiable.
  const data = preview()
  data.findings = [...data.findings,
    { id: 'odd', file: 'third.pdf', origin: 'rule_based', lane: 'unknown_lane', finding_count: 1 }]
  expect(deriveWaterfallImpact(data).complete).toBe(false)
})
