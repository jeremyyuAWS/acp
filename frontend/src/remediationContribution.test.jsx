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
  expect([...container.querySelectorAll('[aria-label="Contribution by source, scaled to original findings"] .contribution-track span')].map(el => el.style.width)).toEqual(['20%', '30%', '50%'])
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

it('adds exact second fallback origin on the same baseline and drills into only its original findings', async () => {
  const secondFallback = { ...snapshot, contributions: { rules: 2, first_ai: 3, fallback_ai: 0, fallback_2_ai: 5 }, findings: snapshot.findings.map(f => f.origin === 'fallback_ai' ? { ...f, origin: 'fallback_2_ai' } : f) }
  const { container } = await mount(Contribution, { snapshot: secondFallback })
  expect([...container.querySelectorAll('[aria-label="Contribution by source, scaled to original findings"] .contribution-track span')].map(el => el.style.width)).toEqual(['20%', '30%', '0%', '50%'])
  expect(container.textContent).toContain('All source bars use the same 10-finding baseline')
  await act(async () => button(container, 'Second fallback additional proposals').click())
  const drawer = container.querySelector('[role=dialog]')
  expect(drawer.querySelectorAll('li')).toHaveLength(5)
  expect(drawer.textContent).not.toContain('first-ai.html')
  expect(drawer.textContent).not.toContain('fixed.html')
})

it('omits absent legacy second fallback data and distinguishes missing count from recorded zero', async () => {
  const { container, render } = await mount(Contribution, { snapshot })
  expect(container.textContent).not.toContain('Second fallback')
  await render({ snapshot: { ...snapshot, coverage: 'partial', contributions: { ...snapshot.contributions, fallback_2_ai: null } } })
  expect(container.textContent).toContain('Second fallback additional proposals: Unavailable')
  await render({ snapshot: { ...snapshot, contributions: { ...snapshot.contributions, fallback_2_ai: 0 } } })
  expect(container.textContent).toContain('Second fallback additional proposals: 0')
})

it('adds second fallback exact finding totals only when supplied and keeps incomplete lineage gated', async () => {
  const complete = { ...snapshot, available: true, first_model_findings: 3, fallback_additional_findings: 0, fallback_2_additional_findings: 5 }
  getRunInsights.mockResolvedValue({ measured_contribution: complete })
  const { container } = await mount(Insights, { scanId: 's1', batchId: 'b1' })
  await act(async () => { const details = container.querySelector('details'); details.open = true; details.dispatchEvent(new Event('toggle')) })
  const row = [...container.querySelectorAll('tr')].find(el => el.textContent.includes('Second fallback: additional suggestions'))
  expect(row.querySelector('td').textContent).toBe('5')
  getRunInsights.mockResolvedValue({ measured_contribution: { ...complete, available: false, coverage: 'partial', fallback_2_additional_findings: null } })
  await act(async () => button(container, 'Refresh saved history').click())
  expect(container.textContent).not.toContain('Second fallback: additional suggestions')
  expect(container.textContent).toContain('Exact finding lineage is incomplete')
})

it('keeps contribution details inside an existing dialog and restores focus to their trigger', async () => {
  getRunInsights.mockResolvedValue({ measured_contribution: snapshot })
  const { container } = await mount(() => createElement('section', { role: 'dialog', 'aria-label': 'Stage evidence' }, createElement(Insights, { scanId: 's1', batchId: 'b1', inlineDrilldown: true })))
  await act(async () => { const details = container.querySelector('details'); details.open = true; details.dispatchEvent(new Event('toggle')) })
  const trigger = button(container, 'Additional fallback proposals')
  await act(async () => { trigger.focus(); trigger.click() })
  expect(container.querySelectorAll('[role=dialog]')).toHaveLength(1)
  const details = container.querySelector('[aria-label="Additional fallback proposals finding details"]')
  expect(details.querySelectorAll('li')).toHaveLength(5)
  expect(details.textContent).not.toContain('fixed.html')
  expect(document.activeElement).toBe(details)
  await act(async () => button(container, 'Back to contribution').click())
  expect(container.querySelector('[aria-label="Additional fallback proposals finding details"]')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  expect(container.querySelectorAll('[role=dialog]')).toHaveLength(1)
})
