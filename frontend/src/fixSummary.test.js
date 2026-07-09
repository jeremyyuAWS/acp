import { describe, it, expect } from 'vitest'
import { scOf, groupFixesByRule, summarizeImpact, totalFixes, fixPhrase, groupMetaForSc } from './fixSummary.js'

// A realistic scan-wide remediation_diff set: 14 image alt fixes, 6 reading-order,
// 3 table headers, 2 link rewrites, 1 contrast — mirrors the customer's example.
const rows = [
  ...Array.from({ length: 14 }, (_, i) => ({ file: `d${i % 3}.docx`, rule_id: '1.1.1', before: 'no alt', after: 'a cat' })),
  ...Array.from({ length: 6 }, () => ({ file: 'a.pdf', rule_id: 'SC_1_3_2' })),
  ...Array.from({ length: 3 }, () => ({ file: 'b.docx', rule_id: 'WCAG_1_3_1' })),
  ...Array.from({ length: 2 }, () => ({ file: 'c.html', rule_id: '2.4.4' })),
  { file: 'e.html', rule_id: '1.4.3' },
]

describe('scOf', () => {
  it('normalises every rule-id form to a bare dotted SC', () => {
    expect(scOf('1.1.1')).toBe('1.1.1')
    expect(scOf('SC_1_1_1')).toBe('1.1.1')
    expect(scOf('WCAG_1_3_2')).toBe('1.3.2')
    expect(scOf('SC 2.4.4')).toBe('2.4.4')
    expect(scOf('')).toBe('')
    expect(scOf(null)).toBe('')
  })
})

describe('totalFixes', () => {
  it('is a straight row count — never fabricated', () => {
    expect(totalFixes(rows)).toBe(26)
    expect(totalFixes([])).toBe(0)
    expect(totalFixes(undefined)).toBe(0)
  })
})

describe('groupFixesByRule', () => {
  it('groups by SC with plain-language phrases, countable vs mass nouns', () => {
    const g = groupFixesByRule(rows)
    const byCat = Object.fromEntries(g.map((e) => [e.category, e]))
    expect(byCat.Images.count).toBe(14)
    expect(byCat.Images.phrase).toBe('Added 14 image descriptions')
    // reading order is a mass noun — no "6 reading orders"
    expect(byCat['Reading order'].count).toBe(6)
    expect(byCat['Reading order'].phrase).toBe('Corrected reading order (6 places)')
    expect(byCat.Tables.phrase).toBe('Added 3 table headers')
    expect(byCat.Links.phrase).toBe('Corrected 2 link descriptions')
    expect(byCat.Contrast.phrase).toBe('Corrected 1 contrast issue')
  })
  it('returns nothing for no fixes (surface hides, never a zero)', () => {
    expect(groupFixesByRule([])).toEqual([])
    expect(groupFixesByRule(null)).toEqual([])
  })
  it('sorts by the fixed presentation order', () => {
    expect(groupFixesByRule(rows).map((e) => e.category)).toEqual(
      ['Images', 'Reading order', 'Tables', 'Links', 'Contrast'])
  })
})

describe('summarizeImpact', () => {
  it('collapses SCs into category tiles', () => {
    const imp = summarizeImpact([
      { rule_id: '2.4.4' }, { rule_id: '2.4.9' },   // both Links
      { rule_id: '1.4.3' }, { rule_id: '1.4.11' },  // both Contrast
      { rule_id: '1.1.1' },
    ])
    const byCat = Object.fromEntries(imp.map((e) => [e.category, e.count]))
    expect(byCat.Links).toBe(2)
    expect(byCat.Contrast).toBe(2)
    expect(byCat.Images).toBe(1)
  })
})

describe('fixPhrase / groupMetaForSc', () => {
  it('pluralises countable nouns and singularises at 1', () => {
    expect(fixPhrase({ ...groupMetaForSc('1.1.1'), count: 1 })).toBe('Added 1 image description')
    expect(fixPhrase({ ...groupMetaForSc('1.1.1'), count: 5 })).toBe('Added 5 image descriptions')
  })
  it('drops the count for a single mass-noun fix', () => {
    expect(fixPhrase({ ...groupMetaForSc('3.1.1'), count: 1 })).toBe('Set document language')
  })
  it('falls back to a generic group for unknown SCs', () => {
    expect(groupMetaForSc('9.9.9').category).toBe('Other')
  })
})
