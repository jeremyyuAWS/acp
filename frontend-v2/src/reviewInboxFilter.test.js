import { describe, it, expect } from 'vitest'
import { reviewHaystack, matchesReviewQuery, filterReviewQueue } from './reviewInboxFilter.js'

// A UI queue item shaped like dbItemToUi output, with a raw hitl_queue row under _raw.
const item = (over = {}) => ({
  id: over.id || 'x1',
  file: 'contract.docx',
  rule: 'WCAG 2.4.4 — Link Purpose (In Context)',
  title: 'DOCX · Link Purpose',
  meta: 'review AI proposal',
  before: 'click here',
  severity: 'CRITICAL',
  ruleId: 'WCAG_2_4_4',
  _raw: { recommendation: 'Describe where the link goes', rule_name: 'Link Purpose' },
  ...over,
})

describe('reviewHaystack — the searchable surface', () => {
  it('spans filename, WCAG number and name, and the recommendation text', () => {
    const h = reviewHaystack(item())
    expect(h).toContain('contract.docx')      // filename
    expect(h).toContain('2.4.4')               // WCAG number
    expect(h).toContain('link purpose')        // WCAG name
    expect(h).toContain('describe where the link goes')  // recommendation (from _raw)
  })

  it('is lowercased so matching is case-insensitive', () => {
    expect(reviewHaystack(item())).toEqual(reviewHaystack(item()).toLowerCase())
  })

  it('is safe on a null item and a bare item with no _raw', () => {
    expect(reviewHaystack(null)).toBe('')
    expect(reviewHaystack({ file: 'a.pdf' })).toBe('a.pdf')
  })
})

describe('matchesReviewQuery', () => {
  it('matches everything on an empty or whitespace query (the no-filter state)', () => {
    expect(matchesReviewQuery(item(), '')).toBe(true)
    expect(matchesReviewQuery(item(), '   ')).toBe(true)
  })

  it('matches on filename', () => {
    expect(matchesReviewQuery(item(), 'contract')).toBe(true)
    expect(matchesReviewQuery(item(), 'invoice')).toBe(false)
  })

  it('matches on WCAG number and on criterion name, case-insensitively', () => {
    expect(matchesReviewQuery(item(), '2.4.4')).toBe(true)
    expect(matchesReviewQuery(item(), 'LINK purpose')).toBe(true)
  })

  it('matches on the AI recommendation text', () => {
    expect(matchesReviewQuery(item(), 'describe where')).toBe(true)
  })

  it('is token-AND and order-independent', () => {
    // both tokens must appear, but not adjacently and in any order
    expect(matchesReviewQuery(item(), 'docx 2.4.4')).toBe(true)
    expect(matchesReviewQuery(item(), '2.4.4 docx')).toBe(true)
    // one token that isn't anywhere fails the whole query
    expect(matchesReviewQuery(item(), 'docx 1.1.1')).toBe(false)
  })
})

describe('filterReviewQueue', () => {
  const q = [
    item({ id: 'a', file: 'contract.docx', rule: 'WCAG 2.4.4 — Link Purpose' }),
    item({ id: 'b', file: 'budget.xlsx', rule: 'WCAG 1.4.3 — Contrast', _raw: {} }),
    item({ id: 'c', file: 'contract.pdf', rule: 'WCAG 1.1.1 — Non-text Content', _raw: {} }),
  ]

  it('returns the same array reference when the query is blank (no needless work)', () => {
    expect(filterReviewQueue(q, '')).toBe(q)
    expect(filterReviewQueue(q, '  ')).toBe(q)
  })

  it('narrows to matching items and preserves priority order', () => {
    const r = filterReviewQueue(q, 'contract')
    expect(r.map((x) => x.id)).toEqual(['a', 'c'])   // order preserved, xlsx dropped
  })

  it('can narrow to a single criterion across files', () => {
    expect(filterReviewQueue(q, '2.4.4').map((x) => x.id)).toEqual(['a'])
  })

  it('returns empty when nothing matches', () => {
    expect(filterReviewQueue(q, 'zzz')).toEqual([])
  })

  it('tolerates a null/empty queue', () => {
    expect(filterReviewQueue(null, 'x')).toEqual([])
    expect(filterReviewQueue([], 'x')).toEqual([])
  })
})
