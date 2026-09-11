import { expect, it } from 'vitest'
import { remediationCategory, outsidePlanRows, aiAppliedUnverified } from './remediationCategories.js'
it.each([
  [{ lane: 'automatic' }, 'automatic'],
  [{ has_proposal: true }, 'approval'],
  [{ primary_reason: 'draft_required' }, 'suggestion'],
  [{ human_only: true, remediation_supported: false }, 'manual'],
  [{ remediation_supported: false }, 'unsupported'],
  [{ processing_blocked: true }, 'blocked'],
  [{ applied: true, status: 'approved' }, 'applied'],
  [{ verified: true }, 'verified'],
  [{ status: 'approved' }, 'blocked'],
  [{ primary_reason: 'ai_disabled' }, 'manual'],
])('classifies evidence without treating approval as verification: %j', (row, category) => {
  expect(remediationCategory(row)).toBe(category)
})
it('matches assessment and plan by file and SC, distinguishes excluded scope, and never guesses from missing rows', () => {
  const rows = [{ file: 'A.pdf', criterion: '1.1.1', finding_count: 4 }, { file: 'B.docx', criterion: '1.3.1', finding_count: 3 }]
  const result = outsidePlanRows(rows, [{ file: 'A.pdf', rule_id: 'SC_1_1_1', finding_count: 2 }], ['A.pdf'])
  expect(result.map(row => row.finding_count)).toEqual([2, 3])
  expect(result[0].reason).toContain('does not prove a fix')
  expect(result[1].reason).toContain('outside the selected plan scope')
  expect(outsidePlanRows(rows, null)).toBeNull()
})

it('AI applied tag requires durable application provenance and stays in the pending category', () => {
  const proposal = { model_call_id: 'call-1', model: 'local-model' }
  expect(aiAppliedUnverified({ has_proposal: true, proposals: [proposal] })).toBe(false)
  expect(aiAppliedUnverified({ applied: true, fixMode: 'ai-assisted' })).toBe(false)
  const row = { _raw: { applied: true, proposals: [proposal] } }
  expect(aiAppliedUnverified(row)).toBe(true)
  expect(remediationCategory(row)).toBe('applied')
  expect(aiAppliedUnverified({ ...row, verified: true })).toBe(false)
  expect(aiAppliedUnverified({ aiApplicationRecord: true })).toBe(true)
})
