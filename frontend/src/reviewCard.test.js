import { describe, it, expect } from 'vitest'
import { buildEvidenceCard } from './reviewCard.js'

describe('buildEvidenceCard — the Evidence Card model', () => {
  it('alt-text item → assisted track, Approve & Apply, real recommendation + confidence basis', () => {
    const c = buildEvidenceCard({
      id: 'i1', scan_id: 's1', file: 'deck.pptx', rule_id: 'SC_1_1_1',
      rule_name: 'Non-text content', approved_value: 'A guide dog in a harness',
    })
    expect(c.sc).toBe('1.1.1')
    expect(c.fmt).toBe('PPTX')
    expect(c.track.track).toBe('assisted')
    expect(c.track.action).toBe('Approve & Apply')
    expect(c.recommendation).toBe('A guide dog in a harness')
    expect(c.confidence.basis).toBeTruthy()          // evidence, never a %
    expect(c.problem).toMatch(/alt-text|description/i)
    expect(c.impact).toEqual({ before: 'Fail', after: 'Pass' })
  })

  it('keyboard item → human track (detect ≠ fix)', () => {
    expect(buildEvidenceCard({ rule_id: '2.1.1', file: 'x.pdf' }).track.track).toBe('human')
  })

  it('deterministic item → auto track (auto-applied, not a review card action)', () => {
    expect(buildEvidenceCard({ rule_id: '1.4.3', file: 'x.docx' }).track.track).toBe('auto')
  })

  it('filters before/after diffs to this criterion only', () => {
    const c = buildEvidenceCard({ rule_id: '1.4.3', file: 'x.docx' }, [
      { rule_id: '1.4.3', before: 'faint', after: 'dark' },
      { rule_id: '2.4.2', before: 'no title', after: 'Title' },
    ])
    expect(c.diffs.length).toBe(1)
    expect(c.diffs[0].after).toBe('dark')
  })

  it('no AI draft → recommendation is null (a judgement item)', () => {
    expect(buildEvidenceCard({ rule_id: '2.1.1', file: 'x.pdf' }).recommendation).toBeNull()
  })
})

describe('buildEvidenceCard — AI proposals (hitl_queue.proposals)', () => {
  const withProposal = (extra = {}, proposals = [
    { locator: '#l1', before: 'click here', proposed_value: 'Download Annual Report (PDF)',
      rationale: "derived from the download target 'Annual-Report.pdf'", source: 'derived from the link target' },
  ]) => buildEvidenceCard({
    id: 'p1', scan_id: 's1', file: 'page.html', rule_id: 'SC_2_4_4',
    rule_name: 'Link Purpose', proposals, ...extra,
  })

  it('a server-side proposal becomes the recommendation the reviewer confirms', () => {
    const c = withProposal()
    expect(c.recommendation).toBe('Download Annual Report (PDF)')
    expect(c.proposal.list).toHaveLength(1)
    expect(c.proposal.list[0].rationale).toMatch(/derived from the download target/)
  })

  it('a proposal outranks a stale approved_value — it is the current recommendation', () => {
    const c = withProposal({ approved_value: 'an older approved value' })
    expect(c.recommendation).toBe('Download Annual Report (PDF)')
  })

  it('falls back to approved_value when there is no proposal', () => {
    const c = buildEvidenceCard({ id: 'x', rule_id: 'SC_2_4_4', approved_value: 'Read the 2026 report' })
    expect(c.recommendation).toBe('Read the 2026 report')
    expect(c.proposal).toBe(null)
  })

  it('a validated proposal is MEDIUM, never High — an AI proposal is not trusted until approved', () => {
    const c = withProposal({ validated: 1 })
    expect(c.proposal.validated).toBe(true)
    expect(c.confidence.level.label).toBe('Medium')
    expect(c.confidence.basis).toMatch(/validated by re-scan/)
  })

  it('an unvalidated proposal is MEDIUM — approve to apply', () => {
    expect(withProposal().confidence.basis).toMatch(/approve to apply/)
  })

  it('a decorative proposal is subjective → LOW (a re-scan can never validate the call)', () => {
    const c = withProposal({ validated: 1 }, [
      { proposed_value: 'Mark as decorative — no alt text needed', kind: 'decorative',
        rationale: "filename 'site-logo.png' looks decorative" },
    ])
    expect(c.proposal.subjective).toBe(true)
    expect(c.confidence.level.label).toBe('Low')
    expect(c.confidence.basis).toMatch(/human judgement/)
  })

  it('a 1.3.3 sensory rewrite is subjective by criterion, whatever its kind', () => {
    const c = buildEvidenceCard({
      id: 's', rule_id: '1.3.3', validated: 1,
      proposals: [{ proposed_value: 'Select the Submit button', rationale: 'relies on colour' }],
    })
    expect(c.proposal.subjective).toBe(true)
    expect(c.confidence.level.label).toBe('Low')
  })

  it('never emits a fabricated percentage (ADR 0016)', () => {
    for (const c of [withProposal(), withProposal({ validated: 1 })]) {
      expect(JSON.stringify(c.confidence)).not.toMatch(/%/)
    }
  })
})
