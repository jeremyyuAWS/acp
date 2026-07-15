import { describe, it, expect } from 'vitest'
import { coverageSummary, statusIn, statusAcross, estateFormats, DOCUMENTS_20 } from './assessCoverage.js'

const filesOf = (...exts) => exts.map((e, i) => ({ file: `doc${i}.${e}`, type: e }))

describe('assessCoverage — capability, format-scoped', () => {
  it('every 20-core criterion resolves to exactly one status per format', () => {
    for (const sc of DOCUMENTS_20) {
      for (const f of ['docx', 'xlsx', 'pptx', 'pdf', 'html']) {
        expect(['auto', 'ai', 'human', 'gap', 'at', 'na']).toContain(statusIn(sc, f))
      }
    }
  })

  it('an all-.xlsx estate is now fully covered: 11 assessable · 0 gaps · 9 N/A (2.4.4 + 2.4.6 closed)', () => {
    const s = coverageSummary(filesOf('xlsx'), { documents: true })
    expect(s.fmts).toEqual(['xlsx'])
    expect(s.assessable).toBe(11)   // + 2.4.4 + 2.4.6 (both now assessed)
    expect(s.human).toBe(0)         // 2.4.4 link-purpose + 2.4.6 labels are both AI-assisted now
    expect(s.gap).toBe(0)           // no buildable gaps left for xlsx
    expect(s.at).toBe(0)
    expect(s.na).toBe(9)
    expect(s.assessable + s.gap + s.at + s.na).toBe(20)
    expect(s.auto + s.ai + s.human).toBe(s.assessable)
  })

  it('an all-.docx estate is now fully covered: 11 assessable · 0 gaps (1.3.2 closed)', () => {
    const s = coverageSummary(filesOf('docx'), { documents: true })
    expect(s.assessable).toBe(11)   // + 1.3.2 reading-order
    expect(s.gap).toBe(0)
    expect(s.assessable + s.gap + s.at + s.na).toBe(20)
  })

  it('mixed doc estate (docx/xlsx/pptx/pdf): gaps collapse into assessable — 12 assessable, 0 gap, 8 N/A', () => {
    const s = coverageSummary(filesOf('docx', 'xlsx', 'pptx', 'pdf'), { documents: true })
    expect(s.assessable).toBe(12)   // union across all four
    expect(s.gap).toBe(0)           // every gap criterion is assessable in SOME present format
    expect(s.na).toBe(8)
    expect(s.assessable + s.gap + s.at + s.na).toBe(20)
  })

  it('an all-.pptx estate is fully covered for what applies (0 gaps)', () => {
    const s = coverageSummary(filesOf('pptx'), { documents: true })
    expect(s.assessable).toBe(12)
    expect(s.gap).toBe(0)
    expect(s.na).toBe(8)
  })

  it('an .html estate: 1.3.2 + 1.4.5 now assessed, only the 2 keyboard criteria remain (needs-AT)', () => {
    const s = coverageSummary(filesOf('html'), { documents: true })
    expect(s.assessable).toBe(18)   // + 1.3.2 + 1.4.5 (both now detected)
    expect(s.gap).toBe(0)           // no buildable gaps left anywhere
    expect(s.at).toBe(2)            // 2.1.1 + 2.1.2 — only static-analysis can't prove these
    expect(s.na).toBe(0)
    expect(s.assessable + s.gap + s.at + s.na).toBe(20)
  })

  it('every doc format now has zero buildable gaps', () => {
    for (const f of ['docx', 'xlsx', 'pptx', 'pdf']) {
      expect(coverageSummary(filesOf(f), { documents: true }).gap, f).toBe(0)
    }
  })

  it('union status prefers assessable over na (gaps are all closed)', () => {
    expect(statusAcross('2.4.6', ['docx', 'pdf'])).toBe('auto')  // auto in docx wins
    expect(statusAcross('2.4.6', ['pdf'])).toBe('ai')            // pdf 2.4.6 now AI-assisted (heading-map proposer)
    expect(statusAcross('2.4.6', ['xlsx'])).toBe('ai')           // xlsx 2.4.6 now AI-assisted (label proposer)
    expect(statusAcross('1.4.4', ['docx'])).toBe('na')           // still not applicable to docx
  })

  it('empty / unknown estate falls back to the four document formats', () => {
    expect(estateFormats([])).toEqual(['docx', 'xlsx', 'pptx', 'pdf'])
    expect(estateFormats([{ file: 'x.zip' }])).toEqual(['docx', 'xlsx', 'pptx', 'pdf'])
  })

  it('the full-catalog view still sums cleanly and is a superset of the 20-core', () => {
    const documents = coverageSummary(filesOf('docx'), { documents: true })
    const all = coverageSummary(filesOf('docx'), { documents: false })
    expect(all.total).toBeGreaterThan(documents.total)
    expect(all.assessable + all.gap + all.at + all.na).toBe(all.total)
  })
})
