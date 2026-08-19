import { describe, it, expect } from 'vitest'
import {
  findingSc, natureOfSc, natureOf, isContrastFinding,
  parseHexes, contrastRatio, contrastEvidence, changeSentence, passesAA,
} from './remediationEvidence.js'

describe('remediationEvidence — success-criterion NATURE (fixes the copy bug)', () => {
  it('classifies contrast / alt-text / images-of-text as VISUAL', () => {
    for (const sc of ['1.1.1', '1.4.3', '1.4.5', '1.4.6', '1.4.9', '1.4.11']) {
      expect(natureOfSc(sc)).toBe('visual')
    }
  })

  it('classifies title / reading-order / language / structure as STRUCTURAL', () => {
    for (const sc of ['2.4.2', '1.3.1', '1.3.2', '3.1.1', '3.1.2']) {
      expect(natureOfSc(sc)).toBe('structural')
    }
  })

  it('reads the SC from any field spelling', () => {
    expect(findingSc({ rule_id: 'WCAG_1.4.3' })).toBe('1.4.3')
    expect(findingSc({ ruleId: 'SC_2_4_2' })).toBe('2.4.2')
    expect(findingSc({ wcag: '1.1.1' })).toBe('1.1.1')
  })

  it('a VISIBLE finding is judged by its criterion, NOT by whether it has coordinates', () => {
    // The whole point: a 1.4.3 contrast finding with no locator/thumb/page is still VISUAL, so it must
    // never be treated as structure/metadata just because we lack geometry for it.
    const contrastNoGeometry = { rule_id: '1.4.3' } // no page, no locator, no thumb
    expect(natureOf(contrastNoGeometry, /* hasAnchor */ false)).toBe('visual')
  })

  it('falls back to the data-availability heuristic ONLY when the criterion is unknown', () => {
    const unknown = { rule_id: '4.1.2' } // not in the nature map
    expect(natureOf(unknown, true)).toBe('visual')     // has an anchor → point at it
    expect(natureOf(unknown, false)).toBe('structural') // no anchor → the old default
  })
})

describe('remediationEvidence — grounded contrast (real values, no fabrication)', () => {
  it('recognises the contrast criteria', () => {
    expect(isContrastFinding({ rule_id: '1.4.3' })).toBe(true)
    expect(isContrastFinding({ rule_id: '1.1.1' })).toBe(false)
  })

  it('parses every hex colour out of a value string, in order', () => {
    expect(parseHexes('#EEEEEE on #FFFFFF')).toEqual(['#EEEEEE', '#FFFFFF'])
    expect(parseHexes('Darken text to #595959')).toEqual(['#595959'])
    expect(parseHexes('no colour here')).toEqual([])
  })

  it('computes the WCAG contrast ratio from the real hexes (matches the detector maths)', () => {
    // Black on white is the reference 21:1; #767676 on white is ~4.5:1 (the AA threshold).
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 0)
    expect(contrastRatio('#767676', '#FFFFFF')).toBeCloseTo(4.5, 1)
  })

  it('builds before/after colour evidence with COMPUTED ratios from the finding\'s own colours', () => {
    const ev = contrastEvidence({ rule_id: '1.4.3', before: '#EEEEEE on #FFFFFF', after: '#767676' })
    expect(ev.fgBefore).toBe('#EEEEEE')
    expect(ev.fgAfter).toBe('#767676')
    expect(ev.bg).toBe('#FFFFFF')                 // the shared background, reused for the after state
    expect(ev.beforeRatio).toBeCloseTo(1.2, 1)
    expect(ev.afterRatio).toBeCloseTo(4.5, 1)
    expect(passesAA(ev.beforeRatio)).toBe(false)  // derived from the real ratio vs the AA threshold
    expect(passesAA(ev.afterRatio)).toBe(true)
  })

  it('does NOT fabricate a ratio when the background is unknown', () => {
    const ev = contrastEvidence({ rule_id: '1.4.3', before: '#D9D9D9', after: '#2F6FED' })
    expect(ev.fgBefore).toBe('#D9D9D9')
    expect(ev.fgAfter).toBe('#2F6FED')
    expect(ev.bg).toBeNull()
    expect(ev.beforeRatio).toBeNull()             // no background → no invented ratio
    expect(ev.afterRatio).toBeNull()
  })

  it('returns null for a non-contrast finding (caller falls back to text before/after)', () => {
    expect(contrastEvidence({ rule_id: '1.1.1', after: 'A bar chart' })).toBeNull()
  })
})

describe('remediationEvidence — the plain "What ACP changed" sentence', () => {
  it('names the colour change and, when grounded, the ratio change — and that nothing else moved', () => {
    const s = changeSentence({ rule_id: '1.4.3', before: '#EEEEEE on #FFFFFF', after: '#767676' })
    expect(s).toContain('Text color changed from #EEEEEE to #767676')
    expect(s).toContain('Contrast increased from 1.2:1 to 4.5:1')
    expect(s).toContain('No text or layout changed')
  })

  it('omits the ratio clause when it cannot be grounded, but still states the colour change', () => {
    const s = changeSentence({ rule_id: '1.4.3', before: '#D9D9D9', after: '#2F6FED' })
    expect(s).toContain('Text color changed from #D9D9D9 to #2F6FED')
    expect(s).not.toContain(':1')                 // no fabricated ratio
  })

  it('falls back to the literal value change for a non-contrast finding', () => {
    expect(changeSentence({ rule_id: '1.1.1', before: 'no alt text', after: 'A bar chart of revenue' }))
      .toBe('Changed from “no alt text” to “A bar chart of revenue”.')
  })

  it('is null when there is no proposed value to describe', () => {
    expect(changeSentence({ rule_id: '1.1.1' })).toBeNull()
  })
})
