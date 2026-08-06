import { describe, it, expect } from 'vitest'
import { trustStates, reviewRequirement } from './reviewCard.js'

// ADR 0019 §3a — the three evidence-based trust axes that replace a confidence label. Every state
// is a checkable enum derived from a real signal; no axis is ever a fabricated number.
describe('ADR 0019 §3a — three verifiable trust axes, no number', () => {
  it('a re-scan-validated grounded fix reads: grounded + re-scan-passed + safe-to-approve', () => {
    const card = { sc: '1.1.1', recommendation: 'A clinician at a desk.',
      proposal: { validated: true, list: [{ grounded: true, rationale: 'text read from the image (OCR)' }] } }
    const t = trustStates(card)
    expect(t.grounding.code).toBe('grounded_in_ocr')
    expect(t.validation.code).toBe('re_scan_passed')
    expect(t.review.code).toBe('safe_to_auto_apply')
  })

  it('an ungrounded visual guess needs human wording review', () => {
    const card = { sc: '1.1.1', recommendation: 'Two people talking.',
      proposal: { validated: false, list: [{ grounded: false, rationale: 'vision description only' }] }, certifiesOnApprove: false }
    const t = trustStates(card)
    expect(t.grounding.code).toBe('visual_interpretation_required')
    expect(t.validation.code).toBe('not_yet_written')
    expect(t.review.code).toBe('human_wording_review')
  })

  it('a chart-label anchored description names chart_labels as the source', () => {
    const card = { sc: '1.1.1', recommendation: 'Bar chart of Q4 revenue.',
      proposal: { validated: false, list: [{ grounded: true, rationale: 'read from the chart label and axis' }] } }
    expect(trustStates(card).grounding.code).toBe('grounded_in_chart_labels')
  })

  it('a finding with NO draft requires manual remediation — the honest routing', () => {
    const card = { sc: '1.1.1', recommendation: null, proposal: { list: [] } }
    expect(reviewRequirement(card, null, { code: 'not_yet_written' }).code).toBe('manual_remediation')
  })

  it('every axis carries a label + a tone, and never a percentage', () => {
    const t = trustStates({ sc: '2.4.4', recommendation: 'Download the 2026 report (PDF)', certifiesOnApprove: true })
    for (const axis of [t.grounding, t.validation, t.review].filter(Boolean)) {
      expect(axis.label).toBeTruthy()
      expect(['ok', 'warn', 'todo']).toContain(axis.tone)
      expect(axis.label).not.toMatch(/\d+\s*%/)
    }
  })
})
