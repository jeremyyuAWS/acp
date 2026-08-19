import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { scopeImpact, coverageGaps } from './scopeImpact.js'

afterEach(unmountAll)
const { default: ScopeImpact } = await import('./ScopeImpact.jsx')

// discovered 12,486 · eligible 6,408 (sum of by_format) · docx+pdf selected → in-scope 5,408.
const ELIG = { discovered: 12486, eligible: 6408, by_format: { docx: 3000, pdf: 2408, pptx: 700, xlsx: 300 } }
const SEL = new Set(['docx', 'pdf'])

describe('scopeImpact (pure)', () => {
  it('returns null with no eligibility data', () => {
    expect(scopeImpact(null, SEL)).toBeNull()
  })

  it('computes the narrowing and the two drops from real aggregates', () => {
    const r = scopeImpact(ELIG, SEL)
    expect(r).toMatchObject({ discovered: 12486, eligible: 6408, inScope: 5408, noMethod: 6078, deselected: 1000, pct: 43 })
    expect(r.funnel.map((s) => [s.key, s.count, s.drop])).toEqual([
      ['discovered', 12486, 0], ['eligible', 6408, 6078], ['inscope', 5408, 1000],
    ])
    expect(r.excluded.map((x) => [x.key, x.count])).toEqual([['nomethod', 6078], ['deselected', 1000]])
  })

  it('falls back to summing by_format when no eligible total is given', () => {
    const { eligible } = scopeImpact({ discovered: 100, by_format: { docx: 40, pdf: 20 } }, new Set(['docx', 'pdf']))
    expect(eligible).toBe(60)
  })

  it('drops the deselected bucket when every format is selected', () => {
    const r = scopeImpact(ELIG, new Set(['docx', 'pdf', 'pptx', 'xlsx']))
    expect(r.deselected).toBe(0)
    expect(r.excluded.map((x) => x.key)).toEqual(['nomethod'])
  })

  it('never fabricates a stage it cannot back — no lifecycle/changed-since keys', () => {
    const keys = scopeImpact(ELIG, SEL).funnel.map((s) => s.key)
    expect(keys).not.toContain('lifecycle')
    expect(keys).not.toContain('queued')
  })
})

// A small catalog with real, uneven coverage: X is docx/pdf only, Y is pptx only, Z is all four.
const CODESET = [
  { code: '1.4.3', name: 'Contrast (Minimum)', formats: ['docx', 'pdf'] },        // X — no pptx, no xlsx
  { code: '2.1.1', name: 'Keyboard', formats: ['pptx'] },                          // Y — pptx only
  { code: '4.1.2', name: 'Name, Role, Value', formats: ['docx', 'pdf', 'pptx', 'xlsx'] }, // Z — everything
]

describe('coverageGaps (pure)', () => {
  it('flags a pptx gap when a docx/pdf-only criterion is selected with pptx', () => {
    const gaps = coverageGaps(CODESET, new Set(['1.4.3']), new Set(['pptx']))
    expect(gaps).toEqual([{ format: 'pptx', count: 1, codes: [{ code: '1.4.3', name: 'Contrast (Minimum)' }] }])
  })

  it('reports one entry per selected format that a selected criterion cannot be checked on', () => {
    // Select X (docx/pdf) + Y (pptx) across all four formats.
    const gaps = coverageGaps(CODESET, new Set(['1.4.3', '2.1.1']), new Set(['docx', 'pdf', 'pptx', 'xlsx']))
    const byFmt = Object.fromEntries(gaps.map((g) => [g.format, g.count]))
    expect(byFmt).toEqual({ docx: 1, pdf: 1, pptx: 1, xlsx: 2 })          // X lacks pptx/xlsx; Y lacks docx/pdf/xlsx
    // most-affected format first
    expect(gaps[0].format).toBe('xlsx')
    expect(gaps.find((g) => g.format === 'xlsx').codes.map((c) => c.code)).toEqual(['1.4.3', '2.1.1'])
  })

  it('returns no gaps when every selected criterion covers every selected format', () => {
    expect(coverageGaps(CODESET, new Set(['4.1.2']), new Set(['docx', 'pdf', 'pptx', 'xlsx']))).toEqual([])
  })

  it('ignores formats and criteria that are not selected', () => {
    // Only docx selected; X covers docx, so no gap even though X lacks pptx.
    expect(coverageGaps(CODESET, new Set(['1.4.3']), new Set(['docx']))).toEqual([])
  })

  it('never invents a gap for a code the catalog has no row for', () => {
    expect(coverageGaps(CODESET, new Set(['9.9.9']), new Set(['pptx']))).toEqual([])
  })

  it('is empty with nothing selected', () => {
    expect(coverageGaps(CODESET, new Set(), new Set())).toEqual([])
    expect(coverageGaps([], new Set(['1.4.3']), new Set(['pptx']))).toEqual([])
  })

  it('accepts arrays as well as Sets for the selections', () => {
    const gaps = coverageGaps(CODESET, ['1.4.3'], ['pptx'])
    expect(gaps).toEqual([{ format: 'pptx', count: 1, codes: [{ code: '1.4.3', name: 'Contrast (Minimum)' }] }])
  })
})

describe('ScopeImpact (component)', () => {
  let container, root
  beforeEach(() => { ;({ container, root } = createTestRoot()) })
  const render = async (props) => { await act(async () => { root.render(createElement(ScopeImpact, props)) }) }

  it('renders nothing without data or with an empty estate', async () => {
    await render({ elig: null, formats: SEL })
    expect(container.textContent.trim()).toBe('')
    await render({ elig: { discovered: 0, by_format: {} }, formats: SEL })
    expect(container.textContent.trim()).toBe('')
  })

  it('draws the funnel stages, counts, drops and the excluded breakdown', async () => {
    await render({ elig: ELIG, formats: SEL })
    expect(container.textContent).toContain('Population funnel')
    expect(container.textContent).toContain('43% of the discovered estate')
    expect(container.textContent).toContain('12,486')
    expect(container.textContent).toContain('6,408')
    expect(container.textContent).toContain('5,408')
    expect(container.textContent).toContain('−6,078')            // the no-method drop
    expect(container.textContent).toContain('Excluded from this run')
    expect(container.textContent).toContain('Inventory only')
    // one progressbar per funnel stage
    expect(container.querySelectorAll('[role=progressbar]').length).toBe(3)
  })

  it('warns about a selected criterion with no method for a selected document type', async () => {
    // Select the docx/pdf-only criterion together with PowerPoint.
    await render({ elig: ELIG, formats: new Set(['docx', 'pdf', 'pptx']), codeset: CODESET, codes: new Set(['1.4.3']) })
    expect(container.querySelector('.scope-gaps')).toBeTruthy()
    expect(container.textContent).toContain('1 selected criterion has no assessment method for PowerPoint')
    expect(container.textContent).toContain('1.4.3')
    expect(container.querySelector('.scope-gaps-ok')).toBeFalsy()
  })

  it('shows the quiet all-covered note when every selected criterion has a method', async () => {
    await render({ elig: ELIG, formats: new Set(['docx', 'pdf', 'pptx', 'xlsx']), codeset: CODESET, codes: new Set(['4.1.2']) })
    expect(container.querySelector('.scope-gaps')).toBeFalsy()
    expect(container.textContent).toContain('Every selected criterion has an assessment method')
  })

  it('shows no gap chrome at all when there is no selection', async () => {
    await render({ elig: ELIG, formats: new Set(['docx']), codeset: CODESET, codes: new Set() })
    expect(container.querySelector('.scope-gaps')).toBeFalsy()
    expect(container.querySelector('.scope-gaps-ok')).toBeFalsy()
  })

  it('renders coverage warnings even before any discovery data (no funnel)', async () => {
    await render({ elig: null, formats: new Set(['pptx']), codeset: CODESET, codes: new Set(['1.4.3']) })
    expect(container.textContent).not.toContain('Population funnel')
    expect(container.textContent).toContain('no assessment method for PowerPoint')
  })
})
