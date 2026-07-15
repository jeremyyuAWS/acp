import { describe, it, expect } from 'vitest'
import {
  coverageSummary, assessmentIn, remediationIn, statusIn, statusAcross,
  isAssessable, isCertifiable, estateFormats, DOCUMENTS_20,
} from './assessCoverage.js'

const filesOf = (...exts) => exts.map((e, i) => ({ file: `doc${i}.${e}`, type: e }))

describe('assessCoverage — two axes (ADR 0023), format-scoped', () => {
  it('every 20-core criterion resolves to exactly one assessment lane per format', () => {
    for (const sc of DOCUMENTS_20) {
      for (const f of ['docx', 'xlsx', 'pptx', 'pdf', 'html']) {
        expect(['auto', 'review', 'human', 'gap', 'at', 'na']).toContain(assessmentIn(sc, f))
        expect(['auto', 'ai', 'human', 'na']).toContain(remediationIn(sc, f))
      }
    }
  })

  it('statusIn is the assessment axis (back-compat alias)', () => {
    expect(statusIn('1.1.1', 'docx')).toBe(assessmentIn('1.1.1', 'docx'))
    expect(statusIn('2.4.2', 'docx')).toBe('auto')
  })

  it('the honest 🟢 rule: 1.1.1 is review (can detect a fail, cannot certify a pass)', () => {
    for (const f of ['docx', 'xlsx', 'pptx', 'pdf']) {
      expect(assessmentIn('1.1.1', f)).toBe('review')   // alt adequacy is a judgement
      expect(remediationIn('1.1.1', f)).toBe('ai')      // …but AI drafts the fix — independent axis
    }
  })

  it('deterministic structural criteria are 🟢 auto-assess + ⚡ auto-remediate', () => {
    for (const f of ['docx', 'xlsx', 'pptx', 'pdf']) {
      expect(assessmentIn('1.4.3', f)).toBe('auto')     // contrast math
      expect(remediationIn('1.4.3', f)).toBe('auto')
      expect(assessmentIn('2.4.2', f)).toBe('auto')     // title present
    }
  })

  it('office 2.1.2 / 4.1.2 are 🟡 review (controls-gated) — mirrors store.REVIEW_FORMATS', () => {
    for (const f of ['docx', 'xlsx', 'pptx']) {
      expect(assessmentIn('2.1.2', f)).toBe('review')
      expect(assessmentIn('4.1.2', f)).toBe('review')
    }
    // pdf keyboard-trap is 🔴/⚪ for now (no pdf control detector wired) — not review.
    expect(assessmentIn('2.1.2', 'pdf')).toBe('na')
  })

  it('Phase 1b review detectors put their criteria in the 🟡 lane at the format level', () => {
    expect(assessmentIn('1.4.1', 'docx')).toBe('review')   // colour-only status / links
    expect(assessmentIn('1.4.1', 'xlsx')).toBe('review')
    expect(assessmentIn('2.4.3', 'pptx')).toBe('review')   // focus order
    expect(assessmentIn('1.4.11', 'pptx')).toBe('review')  // non-text contrast
    expect(assessmentIn('1.4.11', 'docx')).toBe('review')  // docx DrawingML shapes now covered too
    // not built for these formats yet → grey ⚪ N/A, honestly
    expect(assessmentIn('2.4.3', 'docx')).toBe('na')
    expect(assessmentIn('1.4.1', 'pptx')).toBe('na')
  })

  it('static-deck keyboard (pptx 2.1.1) is 🔴 human-only', () => {
    expect(assessmentIn('2.1.1', 'pptx')).toBe('human')
  })

  it('html keyboard criteria stay needs-AT — no static tool can prove them', () => {
    expect(assessmentIn('2.1.1', 'html')).toBe('at')
    expect(assessmentIn('2.1.2', 'html')).toBe('at')
  })

  // Assessment-axis rollups — the three buckets partition the 20 exactly in every estate.
  const EST = {
    // docx/pptx gain the ADR 0024 Tier-A review lanes: docx +1.4.10/1.4.12, pptx +1.4.4/1.4.10/1.4.12.
    docx: { auto: 5, review: 12, human: 0, gap: 0, at: 0, na: 3, certifiable: 5 },
    xlsx: { auto: 5, review: 9, human: 0, gap: 0, at: 0, na: 6, certifiable: 5 },
    pptx: { auto: 5, review: 13, human: 1, gap: 0, at: 0, na: 1, certifiable: 5 },
    pdf: { auto: 3, review: 9, human: 0, gap: 0, at: 0, na: 8, certifiable: 3 },   // +1.4.12 (ADR 0025 Tier A)
    html: { auto: 11, review: 7, human: 0, gap: 0, at: 2, na: 0, certifiable: 11 },
  }
  for (const [fmt, want] of Object.entries(EST)) {
    it(`an all-.${fmt} estate: ${want.auto}🟢 ${want.review}🟡 ${want.human}🔴 ${want.na}⚪ (sums to 20)`, () => {
      const s = coverageSummary(filesOf(fmt), { documents: true })
      expect({ auto: s.auto, review: s.review, human: s.human, gap: s.gap, at: s.at, na: s.na, certifiable: s.certifiable })
        .toEqual(want)
      expect(s.auto + s.review + s.human + s.gap + s.at + s.na).toBe(20)
      expect(s.assessable).toBe(s.auto + s.review)   // 🟢 + 🟡
      expect(s.certifiable).toBe(s.auto)             // honest headline = 🟢 only
    })
  }

  it('mixed doc estate unions to the best lane per criterion (19 assessable, sum 20)', () => {
    const s = coverageSummary(filesOf('docx', 'xlsx', 'pptx', 'pdf'), { documents: true })
    expect(s.auto).toBe(6)
    // Tier A closes the last three union ⚪ (1.4.4 / 1.4.10 / 1.4.12) into the 🟡 review lane.
    expect(s.review).toBe(13)
    expect(s.human).toBe(1)
    expect(s.na).toBe(0)
    expect(s.assessable).toBe(19)
    expect(s.auto + s.review + s.human + s.gap + s.at + s.na).toBe(20)
  })

  it('remediation axis is counted independently (docx: 5⚡ 6🤖 0👤)', () => {
    const s = coverageSummary(filesOf('docx'), { documents: true })
    expect({ remAuto: s.remAuto, remAi: s.remAi, remHuman: s.remHuman }).toEqual({ remAuto: 5, remAi: 6, remHuman: 0 })
  })

  it('union prefers the best assessment lane; a distinct remediation resolver is honored', () => {
    expect(statusAcross('2.4.6', ['docx', 'pdf'], assessmentIn)).toBe('auto')   // 🟢 in docx wins
    expect(statusAcross('2.4.6', ['pdf'], assessmentIn)).toBe('review')          // pdf 2.4.6 is 🟡
    expect(statusAcross('2.4.6', ['docx'], remediationIn)).toBe('auto')          // ⚡ in docx
    expect(statusAcross('2.4.6', ['pdf'], remediationIn)).toBe('ai')             // 🤖 in pdf
  })

  it('isAssessable = 🟢|🟡 (a verdict or a flag); isCertifiable = 🟢 only', () => {
    expect(isAssessable('auto')).toBe(true)
    expect(isAssessable('review')).toBe(true)
    expect(isAssessable('human')).toBe(false)   // 🔴 can't-assess is NOT assessable
    expect(isAssessable('na')).toBe(false)
    expect(isCertifiable('auto')).toBe(true)
    expect(isCertifiable('review')).toBe(false)
  })

  it('empty / unknown estate falls back to the four document formats', () => {
    expect(estateFormats([])).toEqual(['docx', 'xlsx', 'pptx', 'pdf'])
    expect(estateFormats([{ file: 'x.zip' }])).toEqual(['docx', 'xlsx', 'pptx', 'pdf'])
  })

  it('the full-catalog view still sums cleanly and is a superset of the 20-core', () => {
    const documents = coverageSummary(filesOf('docx'), { documents: true })
    const all = coverageSummary(filesOf('docx'), { documents: false })
    expect(all.total).toBeGreaterThan(documents.total)
    expect(all.auto + all.review + all.human + all.gap + all.at + all.na).toBe(all.total)
  })
})
