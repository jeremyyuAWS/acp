import { describe, it, expect } from 'vitest'
import { remediationImpactScope } from './remediationImpactScope.js'

describe('remediation planner population', () => {
  const files = [{ file: 'automatic.docx', rec: { action: 'auto' } },
    { file: 'human.pdf', rec: { action: 'manual' } },
    { file: 'residual.html', remediated_at: 'earlier', issues: [{}] }]
  it('retains human findings and residual work instead of filtering by automatic eligibility', () => {
    expect(remediationImpactScope(files)).toEqual(files)
  })
  it('honors explicit selection and deferrals equally for forecast and execution', () => {
    expect(remediationImpactScope(files, { 'human.pdf': 'inscope' })).toEqual([files[1]])
    expect(remediationImpactScope(files, { 'automatic.docx': 'defer' })).toEqual(files.slice(1))
  })
})
