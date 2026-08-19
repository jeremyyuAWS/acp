// Finding-level remediation-eligible — documents ACP can actually FIX something in, the honest third
// funnel denominator between "assessable" (any supported format) and "remediated". A document counts
// when it has at least one finding whose remediation lane in that file's format is auto or ai; a
// document whose every open finding is human-only (or has no fix lane) is assessable but NOT remediable.
import { describe, it, expect } from 'vitest'
import { remediationEligibleCount, remediationIn } from './assessCoverage.js'

// Sanity-anchor the criteria this test leans on, so a capability-table change surfaces here as an
// explicit failure rather than a silently-wrong count.
describe('lane anchors', () => {
  it('docx 2.4.2 is deterministically auto-fixable', () => {
    expect(remediationIn('2.4.2', 'docx')).toBe('auto')
  })
  it('an unmapped criterion has no fix lane', () => {
    expect(remediationIn('9.9.9', 'docx')).toBe('na')
  })
})

describe('remediationEligibleCount', () => {
  it('counts a document with an auto/ai-fixable finding', () => {
    expect(remediationEligibleCount([{ type: 'docx', issues: [{ wcag: '2.4.2' }] }])).toBe(1)
  })

  it('does not count a document whose only finding has no fix lane', () => {
    expect(remediationEligibleCount([{ type: 'docx', issues: [{ wcag: '9.9.9' }] }])).toBe(0)
  })

  it('does not count a document with no findings', () => {
    expect(remediationEligibleCount([{ type: 'docx', issues: [] }])).toBe(0)
    expect(remediationEligibleCount([{ type: 'docx' }])).toBe(0)
  })

  it('counts a document that has at least one fixable finding among unfixable ones', () => {
    expect(remediationEligibleCount([{ type: 'docx', issues: [{ wcag: '9.9.9' }, { wcag: '2.4.2' }] }])).toBe(1)
  })

  it('normalises the WCAG label form (SC_x_y_z and "x.y.z Name" both resolve)', () => {
    expect(remediationEligibleCount([{ type: 'docx', issues: [{ wcag: 'SC_2_4_2' }] }])).toBe(1)
    expect(remediationEligibleCount([{ type: 'docx', issues: [{ wcag: '2.4.2 Page Titled' }] }])).toBe(1)
  })

  it('resolves format from the filename when type is absent', () => {
    expect(remediationEligibleCount([{ file: 'brief.docx', issues: [{ wcag: '2.4.2' }] }])).toBe(1)
  })

  it('totals across a mixed estate', () => {
    const files = [
      { type: 'docx', issues: [{ wcag: '2.4.2' }] },   // fixable
      { type: 'docx', issues: [{ wcag: '9.9.9' }] },   // not fixable
      { type: 'docx', issues: [] },                    // clean
      { file: 'x.docx', issues: [{ wcag: '2.4.2' }] }, // fixable
    ]
    expect(remediationEligibleCount(files)).toBe(2)
  })

  it('is safe on empty / missing input', () => {
    expect(remediationEligibleCount([])).toBe(0)
    expect(remediationEligibleCount(undefined)).toBe(0)
  })
})
