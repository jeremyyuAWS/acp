import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import { noteAuthChange, _resetAuthEpoch } from './apiIdentity.js'
import Card from './RemediationImpactCard.jsx'
import { getRemediationImpact } from './api.js'
vi.mock('./api.js', () => ({ getRemediationImpact: vi.fn(), saveRemediationImpactPolicy: vi.fn(), assignRemediationImpact: vi.fn(), getRemediationAIDetails: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const result = (low = 11) => ({
  policy: { rule_based: 2, ai: 1 }, active_policy: { rule_based: 2, ai: 1 },
  capabilities: {}, integrity: { complete: true }, open: { findings: 20, files: 1 },
  lanes: Object.fromEntries(['automatic', 'review', 'manual', 'blocked'].map(k => [k, { findings: 0, files: 0 }])),
  file_outlook: {}, files: [], findings: [],
  estimated_impact: { available: true, scope_revision: 's1', assessment_revision: 'a1', configuration_revision: 'c1',
    applicability: { format: 'html', change_family: 'link-label', config_id: 'c1' },
    sample_size: 40, eligible_findings: 20, additional_usable_suggestions_range: [low, low + 1] },
})
beforeEach(() => { vi.clearAllMocks(); _resetAuthEpoch() })
afterEach(unmountAll)
const props = { runId: 'run', myEmail: 'same-owner', scopeFiles: ['a.html'] }

it('ignores superseded scope responses and does not fetch when disclosure opens', async () => {
  const pending = []
  getRemediationImpact.mockImplementation(() => new Promise(resolve => pending.push(resolve)))
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Card, props)))
  await act(async () => pending[0](result()))
  expect(container.textContent).toContain('11–12')
  await act(async () => root.render(createElement(Card, { ...props, scopeFiles: ['b.html'] })))
  expect(container.textContent).not.toContain('11–12')
  await act(async () => root.render(createElement(Card, { ...props, scopeFiles: ['c.html'] })))
  await act(async () => pending[1](result(15)))
  expect(container.textContent).not.toContain('15–16')
  await act(async () => pending[2](result(17)))
  expect(container.textContent).toContain('17–18')
  const summary = [...container.querySelectorAll('summary')].find(n => n.textContent === 'Estimated extra AI help and cost')
  await act(async () => summary.click())
  expect(getRemediationImpact).toHaveBeenCalledTimes(3)
})

it('rejects in-flight responses after logout and replacement of the same email session', async () => {
  const pending = []
  getRemediationImpact.mockImplementation(() => new Promise(resolve => pending.push(resolve)))
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Card, props)))
  noteAuthChange('old-token', null)
  noteAuthChange(null, 'new-token')
  await act(async () => pending[0](result()))
  expect(container.textContent).not.toContain('11–12')
  await act(async () => root.render(createElement(Card, props)))
  await act(async () => pending[1](result(17)))
  expect(container.textContent).toContain('17–18')
  noteAuthChange('new-token', null)
  await act(async () => root.render(createElement(Card, props)))
  expect(container.textContent).not.toContain('17–18')
})

it('hides estimates immediately when policy changes while the new preview is pending', async () => {
  getRemediationImpact.mockResolvedValueOnce(result()).mockImplementation(() => new Promise(() => {}))
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Card, props)))
  expect(container.textContent).toContain('11–12')
  const review = [...container.querySelectorAll('label')].find(n => n.textContent.includes('Review every change'))
  await act(async () => review.querySelector('input').click())
  expect(container.textContent).not.toContain('11–12')
})
