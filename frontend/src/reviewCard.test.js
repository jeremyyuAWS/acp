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
