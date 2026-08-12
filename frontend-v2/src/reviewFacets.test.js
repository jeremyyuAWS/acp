import { describe, it, expect } from 'vitest'
import { itemSeverity, itemCriterion, reviewFacets, applyReviewFilters, groupReviewByFile, worstSeverity } from './reviewInboxFilter.js'

const Q = [
  { id: 'a', file: 'x.docx', rule: '1.1.1 — Non-text Content', severity: 'CRITICAL', _raw: { recommendation: 'write alt text' } },
  { id: 'b', file: 'y.docx', rule: '2.4.4 — Link Purpose', severity: 'SERIOUS', _raw: { recommendation: 'name the link' } },
  { id: 'c', file: 'x.docx', rule: '1.1.1 — Non-text Content', severity: 'MODERATE', _raw: {} },
]

describe('review inbox facets + filters', () => {
  it('reads severity and criterion off an item', () => {
    expect(itemSeverity(Q[0])).toBe('CRITICAL')
    expect(itemCriterion(Q[0])).toBe('1.1.1')
    expect(itemCriterion({ _raw: { rule_name: '2.4.6 Headings and Labels' } })).toBe('2.4.6')
    expect(itemCriterion({ ruleId: 'DOCX-ALT-001' })).toBe('')   // no WCAG number present
  })

  it('facets offer only what is present, severities worst-first, criteria numeric', () => {
    const f = reviewFacets(Q)
    expect(f.severities).toEqual([
      { key: 'CRITICAL', count: 1 }, { key: 'SERIOUS', count: 1 }, { key: 'MODERATE', count: 1 },
    ])
    expect(f.criteria).toEqual([{ key: '1.1.1', count: 2 }, { key: '2.4.4', count: 1 }])
  })

  it('filters by severity, by criterion, and composes with search — order preserved', () => {
    expect(applyReviewFilters(Q, { severity: 'CRITICAL' }).map((x) => x.id)).toEqual(['a'])
    expect(applyReviewFilters(Q, { criterion: '1.1.1' }).map((x) => x.id)).toEqual(['a', 'c'])
    expect(applyReviewFilters(Q, { query: 'link' }).map((x) => x.id)).toEqual(['b'])
    expect(applyReviewFilters(Q, { severity: 'MODERATE', criterion: '1.1.1' }).map((x) => x.id)).toEqual(['c'])
  })

  it('no filters returns everything (the default state)', () => {
    expect(applyReviewFilters(Q, {})).toHaveLength(3)
    expect(applyReviewFilters(Q, { severity: null, criterion: null, query: '' })).toHaveLength(3)
  })
})

describe('review inbox grouping (by file)', () => {
  it('groups by file, files in first-appearance order, items in queue order', () => {
    const g = groupReviewByFile(Q)
    expect(g.map((x) => x.file)).toEqual(['x.docx', 'y.docx'])   // x first — its item leads the queue
    expect(g[0].items.map((i) => i.id)).toEqual(['a', 'c'])      // both x.docx findings, in order
    expect(g[0].count).toBe(2)
    expect(g[1].items.map((i) => i.id)).toEqual(['b'])
  })

  it('surfaces each file’s WORST severity for the group header', () => {
    const g = groupReviewByFile(Q)
    expect(g[0].worst).toBe('CRITICAL')   // x.docx has CRITICAL + MODERATE
    expect(g[1].worst).toBe('SERIOUS')
    expect(worstSeverity([{ severity: 'MINOR' }, { severity: 'SERIOUS' }, { severity: 'MODERATE' }])).toBe('SERIOUS')
    expect(worstSeverity([])).toBe(null)
  })

  it('is a no-op-safe transform of the filtered queue', () => {
    // Grouping the RESULT of a filter keeps only what survived it — grouping composes with filters.
    const filtered = applyReviewFilters(Q, { severity: 'CRITICAL' })
    const g = groupReviewByFile(filtered)
    expect(g.map((x) => x.file)).toEqual(['x.docx'])
    expect(g[0].items.map((i) => i.id)).toEqual(['a'])
    expect(groupReviewByFile([])).toEqual([])
  })
})
