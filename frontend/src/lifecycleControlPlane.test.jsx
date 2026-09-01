import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import LifecycleEstateSummary from './LifecycleEstateSummary.jsx'
import LifecycleRuleLedger from './LifecycleRuleLedger.jsx'
import LifecycleEvidencePanel from './LifecycleEvidencePanel.jsx'

describe('lifecycle control plane', () => {
  it('renders a reconciled, labeled estate breakdown and safety boundary', () => {
    const html = renderToStaticMarkup(<LifecycleEstateSummary summary={{
      total: 10, reconciled_total: 10, assessment_excluded: 3,
      counts: { active: 5, already_archived: 1, archive_candidate: 2, delete_candidate: 0,
        deleted: 0, exempt: 1, reactivated: 0, unevaluable: 1, failed: 0 },
    }} />)
    expect(html).toContain('10 of 10 files reconciled')
    expect(html).toContain('Archive candidate')
    expect(html).toContain('Recommendations only')
    expect(html).toContain('disposition candidates excluded from Assess')
  })

  it('does not collapse zero matches into an ambiguous empty state', () => {
    const html = renderToStaticMarkup(<LifecycleRuleLedger rules={[{
      policy_id: 'p1', policy_version: 3, name: 'Legacy files', priority: 1,
      evaluated: 20, matched: 0, skipped: 4, unevaluable: 2, conflicts: 1,
      proposed_action: 'archive', evaluated_at: '2026-09-01T00:00:00Z',
    }]} />)
    expect(html).toContain('Legacy files')
    expect(html).toContain('20')
    expect(html).toContain('matched zero files')
    expect(html).toContain('Unevaluable')
  })

  it('shows actual and threshold evidence with policy version', () => {
    const html = renderToStaticMarkup(<LifecycleEvidencePanel file={{
      file: 'old.docx', lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
      evaluations: [{ evaluation_id: 'e1', policy_id: 'p1', policy_version: 2, result: 'matched',
        evidence: { conditions: [{ field: 'modified_age_days', observed_value: 730,
          op: 'gte', value: 365, reason: '730 is at least 365' }] } }],
    }} />)
    expect(html).toContain('version 2')
    expect(html).toContain('actual 730')
    expect(html).toContain('required gte 365')
    expect(html).toContain('class="panel lifecycle-evidence-panel"')
  })
})
