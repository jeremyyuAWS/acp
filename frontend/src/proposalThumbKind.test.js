import { describe, it, expect } from 'vitest'
import { firstKind, isPageThumb, thumbSize, thumbAlt, buildEvidenceCard } from './reviewCard.js'

// A reading-order proposal's thumbnail is a whole rendered PDF page; every other proposal's is
// an image embedded in the document. They need different sizes and — this being an
// accessibility product — different alt text. "Image needing alt text" on a page render is
// precisely the kind of inaccurate alt this tool exists to find.

const item = (kind) => ({ proposals: [{ proposed_value: 'v', ...(kind ? { kind } : {}) }] })

describe('firstKind', () => {
  it('reads the kind off the first proposal', () => {
    expect(firstKind(item('reading-order'))).toBe('reading-order')
    expect(firstKind(item('decorative'))).toBe('decorative')
  })
  it('is null when absent, so callers fall back to the image treatment', () => {
    expect(firstKind(item())).toBeNull()
    expect(firstKind({})).toBeNull()
    expect(firstKind(null)).toBeNull()
  })
})

describe('a page is shown at page size, an image at image size', () => {
  it('classifies only reading-order as a page', () => {
    expect(isPageThumb('reading-order')).toBe(true)
    expect(isPageThumb('decorative')).toBe(false)
    expect(isPageThumb(null)).toBe(false)
    expect(isPageThumb(undefined)).toBe(false)
  })

  it('renders a page larger than an image — 96px of a page is unreadable', () => {
    expect(thumbSize('reading-order')).toBe(240)
    expect(thumbSize('reading-order')).toBeGreaterThan(thumbSize('decorative'))
    expect(thumbSize('reading-order', 96)).toBeGreaterThan(96)
  })

  it('leaves the image size to the caller', () => {
    expect(thumbSize(null)).toBe(84)          // WhyReview
    expect(thumbSize(null, 96)).toBe(96)      // EvidenceCard
    expect(thumbSize('decorative', 96)).toBe(96)
  })
})

describe('the evidence image describes what it actually depicts', () => {
  it('calls a page a page, not an image needing alt text', () => {
    const alt = thumbAlt('reading-order', 'policy.pdf')
    expect(alt).toMatch(/page of policy\.pdf/)
    expect(alt).not.toMatch(/Image needing alt text/)
  })

  it('calls an embedded image an image', () => {
    expect(thumbAlt('decorative', 'deck.pptx')).toBe('Image needing alt text in deck.pptx')
    expect(thumbAlt(null, 'deck.pptx')).toBe('Image needing alt text in deck.pptx')
  })

  it('never renders "undefined" when the filename is missing', () => {
    expect(thumbAlt(null, undefined)).not.toMatch(/undefined/)
    expect(thumbAlt('reading-order', '')).not.toMatch(/undefined/)
  })
})

describe('the evidence card carries the kind through', () => {
  it('exposes thumbKind so EvidenceCard can size and describe the thumb', () => {
    const card = buildEvidenceCard({ id: 1, rule_id: 'SC_1_3_2', file: 'a.pdf',
                                     proposals: [{ proposed_value: '1. Title', kind: 'reading-order' }] })
    expect(card.thumbKind).toBe('reading-order')
    expect(thumbSize(card.thumbKind, 96)).toBe(240)
  })

  it('is null for an ordinary alt-text item', () => {
    const card = buildEvidenceCard({ id: 2, rule_id: 'SC_1_1_1', file: 'a.pptx',
                                     proposals: [{ proposed_value: 'A chart' }] })
    expect(card.thumbKind).toBeNull()
  })
})
