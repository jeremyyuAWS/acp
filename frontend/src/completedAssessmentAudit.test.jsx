import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'
import CompletedStageDetails, { completedAssessSnapshot } from './CompletedStageDetails.jsx'

const saved = { stage: 'assess', assessment_summary: { findings_recorded: 920,
  domain_reconciliation: { total: 26, buckets: { assessed: 26 } } },
  domain_reconciliation: { total: 0, buckets: { assessed: 0 } } }

describe('immutable completed assessment audit', () => {
  it('retains sealed findings and document totals despite newer mutable values', () => {
    const snap = completedAssessSnapshot(saved)
    expect(snap.kpis.findings_so_far).toBe(920)
    expect(snap.kpis.completed).toBe(26)
    const html = renderToStaticMarkup(<CompletedStageDetails snapshot={saved} />)
    expect(html).toContain('920 accessibility findings recorded')
    expect(html).toContain('26 of 26 eligible documents finalized')
  })
  it('shows unavailable for historical manifests without audit counts, never zero', () => {
    const html = renderToStaticMarkup(<CompletedStageDetails snapshot={{ stage: 'assess',
      domain_reconciliation: { total: 26, buckets: { assessed: 26 } } }} />)
    expect(html).toContain('original findings total is unavailable')
    expect(html).not.toContain('0 accessibility findings recorded')
  })
  it('retains a measured zero as a real assessment result', () => {
    expect(completedAssessSnapshot({ ...saved, assessment_summary: {
      ...saved.assessment_summary, findings_recorded: 0 } }).kpis.findings_so_far).toBe(0)
  })
})
