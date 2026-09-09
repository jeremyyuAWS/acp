import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, it, expect } from 'vitest'
import Disclosure from './RemediationEstimateDisclosure.jsx'
const render = props => renderToStaticMarkup(<Disclosure aiEnabled {...props} />)
const estimate = {
  scope_revision: 'scope-1', assessment_revision: 'assessment-1', configuration_revision: 'exact-model-reviewer',
  available: true, additional_usable_suggestions_range: [59, 86], eligible_findings: 100,
  sample_size: 40, evaluation_version: 'v1', evaluated_at: '2026-09-07', expires_at: '2026-09-20',
  applicability: { format: 'html', change_family: 'link-label', config_id: 'exact-model-reviewer' },
  uncertainty: '95% interval for expected count', expected_provider_cost_range_usd: ['2', '3'],
}
describe('representative estimate disclosure', () => {
  it('stays absent for rules only', () => expect(render({ aiEnabled: false })).toBe(''))
  it('shows unavailable without invented zeros', () => {
    const html = render({})
    expect(html).toContain('Not enough applicable evidence')
    expect(html).not.toContain('$0')
    expect(html).toContain('no paid AI requests')
  })
  it('labels the range, sample, date and applicability', () => {
    const html = render({ estimate })
    for (const value of ['59–86', '40 evaluated', 'v1', '2026-09-20', 'exact-model-reviewer', '95% interval', '$2.00–$3.00']) expect(html).toContain(value)
    expect(html).toContain('<summary')
  })
  it('hides old numbers during scope refresh', () => {
    const html = render({ estimate, loading: true })
    expect(html).toContain('Updating estimate')
    expect(html).not.toContain('59–86')
  })
  it('does not convert unknown charges into free work', () => {
    const html = render({ estimate: { ...estimate, expected_provider_cost_range_usd: null } })
    expect(html).toContain('complete, settled charges are required')
    expect(html).not.toContain('$0')
  })
})

it('refuses numbers without immutable assessment and configuration bindings', () => {
  expect(render({ estimate: { ...estimate, assessment_revision: null } })).not.toContain('59–86')
  expect(render({ estimate: { ...estimate, configuration_revision: 'other-model' } })).not.toContain('59–86')
})
