import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Card from './WorkflowStageActivityCard.jsx'
it('names accounted findings and the missing outcome instead of claiming fix completion', () => {
  const html = renderToStaticMarkup(<Card snapshot={{ stage: 'remediate', state: 'processing_complete',
    reconciliation: {total:2,accounted:2,exact:true}, integrity:{ok:false},
    domain_reconciliation:{unit:'assessed findings',total:8,accounted:7,exact:false,
      buckets:{resolved_verified:4,awaiting_review:3}} }} />)
  expect(html).toContain('assessed findings accounted for')
  expect(html).toContain('1 assessed finding still lack a recorded outcome')
  expect(html).toContain('88% accounted for')
  expect(html).not.toContain('88% complete')
})

import { alignRemediationAssessment } from './canonicalStageCard.js'
import Stack from './WorkflowStageStack.jsx'
it('shows all 32 Assess findings and makes the 29-item historical breakdown add up without inventing fixes', () => {
  const original = { stage: 'remediate', execution_id: 'rem', workflow_revision: 1, state: 'processing_complete',
    reconciliation: { total: 4, accounted: 4, exact: true }, integrity: { ok: false },
    domain_reconciliation: { unit: 'assessed findings', total: 29, accounted: 22, exact: false,
      buckets: { resolved_verified: 13, awaiting_review: 9 } } }
  const aligned = alignRemediationAssessment(original, 32)
  expect(aligned.domain_reconciliation.total).toBe(32)
  expect(Object.values(aligned.domain_reconciliation.buckets).reduce((a,b) => a+b,0)).toBe(32)
  expect(aligned.domain_reconciliation.buckets).toMatchObject({ resolved_verified: 13, awaiting_review: 9,
    awaiting_recorded_outcome: 7, not_in_remediation_breakdown: 3 })
  expect(original.domain_reconciliation.total).toBe(29)
  const html = renderToStaticMarkup(<Stack lineage={{scan_id:'scan', workflow_revision:1, stages:[original]}}
    assessmentFindings={{scanId:'scan', total:32}} />)
  expect(html).toContain('22 of 32')
  expect(html).toContain('Not in remediation breakdown')
  expect(html).toContain('10 assessed findings still lack a recorded outcome')
  const other = renderToStaticMarkup(<Stack lineage={{scan_id:'scan',workflow_revision:1,stages:[original]}}
    assessmentFindings={{scanId:'other-scan',total:32}} />)
  expect(other).not.toContain('of 32')
})

import { omittedAssessmentGroups } from './canonicalStageCard.js'
it('traces omitted findings to recorded file/SC evidence and refuses inconsistent evidence', () => {
  const snapshot = { domain_reconciliation: { total: 2 } }
  const audit = { findings_recorded: 2, finding_groups: [{file:'one.pdf',rule_id:'SC_2_4_2',finding_count:2}] }
  const rows = [{file:'one.pdf',findings:[{sc:'2.4.2'},{sc:'2.4.2'},{sc:'1.4.1'}]}]
  expect(omittedAssessmentGroups(snapshot,audit,rows)).toEqual([{file:'one.pdf',sc:'1.4.1',count:1}])
  expect(omittedAssessmentGroups(snapshot,audit,[{file:'different.pdf',findings:rows[0].findings}])).toEqual([])
  expect(omittedAssessmentGroups(snapshot,{...audit,findings_recorded:3},rows)).toEqual([])
  const html = renderToStaticMarkup(<Card snapshot={{stage:'remediate',state:'processing_complete',
    domain_reconciliation:{total:3,accounted:2,buckets:{resolved_verified:2}},
    omitted_assessment_groups:[{file:'one.pdf',sc:'1.4.1',count:1}]}} />)
  expect(html).toContain('Processing complete')
  expect(html).toContain('2 with recorded outcomes + 1 awaiting an outcome = 3 assessed findings')
  expect(html).toContain('one.pdf')
  expect(html).toContain('SC 1.4.1')
})
