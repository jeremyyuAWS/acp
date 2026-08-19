import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { scopeImpact } from './scopeImpact.js'

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
})
