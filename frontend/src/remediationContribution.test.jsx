import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Contribution from './RemediationContribution.jsx'
import Insights from './RemediationRunInsights.jsx'
import { getRunInsights } from './remediationRunInsightsClient.js'
vi.mock('./remediationRunInsightsClient.js', () => ({ getRunInsights: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
beforeEach(() => vi.resetAllMocks())
const snapshot = { contract_version: 'remediation-contribution.v1', coverage: 'complete', baseline_total: 10, selected_file_count: 2, snapshot_id: 'snapshot-1', revision: 1, contributions: { rules: 2, first_ai: 3, fallback_ai: 5 }, outcomes: { fixed: 2, awaiting_review: 5, approved: 0, unresolved: 3, processing: 0, unavailable: 0 }, reviewer: { checked_proposals: 7 }, findings: [
  ...Array.from({ length: 5 }, (_, n) => ({ finding_id: `f${n}`, file: `fallback-${n}.html`, rule_id: '1.1.1', state: 'awaiting_review', origin: 'fallback_ai', proposal_id: 'one-proposal' })),
  { finding_id: 'fixed', file: 'fixed.html', state: 'fixed', origin: 'rules' },
  { finding_id: 'fixed-2', file: 'fixed-2.html', state: 'fixed', origin: 'rules' },
  ...Array.from({ length: 3 }, (_, n) => ({ finding_id: `unresolved-${n}`, file: 'first-ai.html', state: 'unresolved', origin: 'first_ai' })),
] }
async function mount(component, props) {
  const { root, container } = createTestRoot()
  const render = next => act(async () => root.render(createElement(component, { ...props, ...next })))
  await render()
  return { container, render }
}
const button = (container, label) => [...container.querySelectorAll('button')].find(el => el.textContent === label)
it('uses one baseline scale and drills into the same five fallback findings across revisions', async () => {
  const { container, render } = await mount(Contribution, { snapshot })
  expect([...container.querySelectorAll('.contribution-track span')].map(el => el.style.width)).toEqual(['20%', '30%', '50%'])
  expect(container.textContent).toContain('AI review checked 7 proposals')
  expect(container.querySelectorAll('table')).toHaveLength(2)
  await act(async () => button(container, 'Additional fallback proposals').click())
  expect(container.querySelector('[role=dialog]').querySelectorAll('li')).toHaveLength(5)
  expect(container.querySelector('[role=dialog]').textContent).not.toContain('fixed.html')
  await render({ snapshot: { ...snapshot, revision: 2, findings: snapshot.findings.map(f => ({ ...f, proposal_id: 'revised-proposal' })) } })
  expect(container.querySelector('[role=dialog]').querySelectorAll('li')).toHaveLength(5)
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
  await act(async () => button(container, 'Verified fixes').click())
  expect(container.querySelector('[role=dialog]').querySelectorAll('li')).toHaveLength(2)
  expect(container.querySelector('[role=dialog]').textContent).toContain('fixed.html')
})
it('shows missing history as unavailable and identifies partial coverage', async () => {
  const { container, render } = await mount(Contribution, {})
  expect(container.textContent).toContain('missing evidence is not a zero count')
  expect(container.querySelector('table')).toBeNull()
  await render({ snapshot: { ...snapshot, coverage: 'partial', contributions: { rules: null, first_ai: 3, fallback_ai: 5 } } })
  expect(container.textContent).toContain('Partial coverage')
  expect(container.textContent).toContain('Rules: Unavailable')
})
it('keeps a successful snapshot through refresh and failure but clears it on a run change', async () => {
  getRunInsights.mockResolvedValue({ measured_contribution: snapshot })
  const { container, render } = await mount(Insights, { scanId: 's1', batchId: 'b1' })
  await act(async () => { const details = container.querySelector('details'); details.open = true; details.dispatchEvent(new Event('toggle')) })
  let reject
  getRunInsights.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
  await act(async () => button(container, 'Refresh saved history').click())
  expect(container.textContent).toContain('10 original findings')
  expect(container.textContent).toContain('Refreshing saved history')
  await act(async () => reject(new Error('offline')))
  expect(container.textContent).toContain('10 original findings')
  expect(container.textContent).toContain('Refresh failed')
  getRunInsights.mockImplementationOnce(() => new Promise(() => {}))
  await render({ batchId: 'b2' })
  expect(container.textContent).not.toContain('10 original findings')
  expect(container.querySelector('.remediation-contribution')).toBeNull()
})
