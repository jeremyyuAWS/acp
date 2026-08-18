import { describe, it, expect } from 'vitest'
import {
  scanCriteria, scanDocTypes, frozenScopeChip, frozenScopeSummary, scopeImpact,
} from './frozenScope.js'

// The per-scan FROZEN scope helpers (R6 / Phase 3b). The load-bearing case throughout is that a
// null `scan_scope` means NO RESTRICTION — the WHOLE core — and never "nothing". Reading it as an
// empty scope would be the reassuring lie every scope module here exists to refuse.
const CORE = new Set(['1.1.1', '1.4.3', '2.4.4', '2.4.6'])

describe('scanCriteria', () => {
  it('null map is the whole core, not an empty set', () => {
    expect(scanCriteria(null, CORE)).toEqual(CORE)
    expect(scanCriteria(undefined, CORE).size).toBe(4)
  })
  it('a map is exactly its keys', () => {
    expect(scanCriteria({ '1.1.1': ['docx'], '1.4.3': ['pdf'] }, CORE)).toEqual(new Set(['1.1.1', '1.4.3']))
  })
})

describe('scanDocTypes', () => {
  it('null when unrestricted, so the caller says "all types" rather than inventing a list', () => {
    expect(scanDocTypes(null)).toBeNull()
  })
  it('is the sorted, de-duplicated union of the format lists', () => {
    expect(scanDocTypes({ '1.1.1': ['pdf', 'docx'], '1.4.3': ['docx'] })).toEqual(['docx', 'pdf'])
  })
})

describe('frozenScopeChip', () => {
  it('labels the unrestricted scan too, and does not mark it narrow', () => {
    expect(frozenScopeChip(null, CORE)).toEqual({ text: 'all 4 criteria', restricted: false })
  })
  it('a full-core map is not restricted', () => {
    const full = { '1.1.1': [], '1.4.3': [], '2.4.4': [], '2.4.6': [] }
    expect(frozenScopeChip(full, CORE).restricted).toBe(false)
  })
  it('a subset is restricted and states n of core', () => {
    const c = frozenScopeChip({ '1.1.1': ['docx'], '1.4.3': ['docx'] }, CORE)
    expect(c).toEqual({ text: '2 of 4 criteria', restricted: true })
  })
})

describe('frozenScopeSummary', () => {
  it('the unrestricted branch is a fact about the run, worded as one', () => {
    expect(frozenScopeSummary(null, CORE)).toMatch(/all 4 document-core criteria — no scope narrowing/)
  })
  it('names the count and the doc types', () => {
    const s = frozenScopeSummary({ '1.1.1': ['docx', 'pdf'], '1.4.3': ['docx'] }, CORE)
    expect(s).toContain('2 of 4 document-core criteria')
    expect(s).toContain('docx, pdf')
  })
})

describe('scopeImpact', () => {
  it('is exact: added and dropped criteria vs the next scope', () => {
    const prev = { '1.1.1': ['docx'], '1.4.3': ['docx'], '2.4.4': ['pdf'] }
    const next = new Set(['1.1.1', '1.4.3', '2.4.6'])   // drops 2.4.4, adds 2.4.6
    const im = scopeImpact(prev, next, CORE)
    expect(im.prevCount).toBe(3)
    expect(im.nextCount).toBe(3)
    expect(im.added).toEqual(['2.4.6'])
    expect(im.dropped).toEqual(['2.4.4'])
    expect(im.changed).toBe(true)
  })
  it('a null frozen scope is compared as the whole core — so a narrowed global scope shows as drops', () => {
    const im = scopeImpact(null, new Set(['1.1.1', '1.4.3']), CORE)
    expect(im.prevCount).toBe(4)
    expect(im.dropped).toEqual(['2.4.4', '2.4.6'])
    expect(im.added).toEqual([])
    expect(im.changed).toBe(true)
  })
  it('equal scopes report no change', () => {
    const im = scopeImpact({ '1.1.1': ['docx'], '1.4.3': ['docx'] }, new Set(['1.1.1', '1.4.3']), CORE)
    expect(im.changed).toBe(false)
    expect(im.added).toEqual([])
    expect(im.dropped).toEqual([])
  })
})
