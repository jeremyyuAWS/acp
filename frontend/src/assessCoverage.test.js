import { describe, it, expect } from 'vitest'
import {
  coverageSummary, assessmentGaps, assessmentIn, remediationIn, statusIn, statusAcross,
  isAssessable, isCertifiable, estateFormats, DOCUMENTS_20, AT_REASON,
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
    // pdf 4.1.2 reaches the same 🟡 by a different route: not controls-gated but coverage-
    // gated. The AcroForm detector always runs and is exact over the fields it reads, yet it
    // never sees the tagged-structure components the criterion also covers, so a clean scan
    // cannot certify. Its REMEDIATION lane is ⚡ auto regardless — the axes are independent.
    expect(assessmentIn('4.1.2', 'pdf')).toBe('review')
    expect(remediationIn('4.1.2', 'pdf')).toBe('auto')
  })

  it('Phase 1b review detectors put their criteria in the 🟡 lane at the format level', () => {
    expect(assessmentIn('1.4.1', 'docx')).toBe('review')   // colour-only status / links
    expect(assessmentIn('1.4.1', 'xlsx')).toBe('review')
    expect(assessmentIn('2.4.3', 'pptx')).toBe('review')   // focus order
    expect(assessmentIn('1.4.11', 'pptx')).toBe('review')  // non-text contrast
    expect(assessmentIn('1.4.11', 'docx')).toBe('review')  // docx DrawingML shapes now covered too
    // not built for these formats yet → grey ⚪ N/A, honestly
    expect(assessmentIn('2.4.3', 'docx')).toBe('na')
    expect(assessmentIn('1.4.1', 'pptx')).toBe('review')  // colour-only hyperlinks
  })

  it('2.4.6 is 🟡 review on every document format — level-stepping is not descriptiveness', () => {
    // docx was 🟢 until 997b7d0: its only detector (DOCX_HEADING_SKIP) decides whether heading
    // LEVELS step by one, which is strictly narrower than "do headings DESCRIBE their topic".
    // The fixer closed level gaps, the re-scan came back clean, and that was read as proof the
    // criterion was met — a closed, self-confirming loop that certified a pass it could not
    // support. Pinned per format so a future edit cannot quietly restore the 🟢.
    // html joined them: scanner.HTML_HEADING_SKIP is the same level check under another name,
    // and _fix_heading_skip the same clamp, so the same closed loop certified the same pass it
    // could not support. All five formats now agree.
    for (const f of ['docx', 'xlsx', 'pptx', 'pdf', 'html']) {
      expect(assessmentIn('2.4.6', f)).toBe('review')
      expect(remediationIn('2.4.6', f)).not.toBe('na')   // remediation lane is untouched
    }
    // ⚡ heading-skip closure still proven on both formats whose fixer is deterministic.
    expect(remediationIn('2.4.6', 'docx')).toBe('auto')
    expect(remediationIn('2.4.6', 'html')).toBe('auto')
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
    // docx is 4🟢/13🟡 rather than 5/12 because 2.4.6 moved 🟢→🟡 in 997b7d0 (see the 2.4.6 test above).
    docx: { auto: 4, review: 13, human: 0, gap: 0, at: 0, na: 3, certifiable: 4 },
    // xlsx is 10🟡/5⚪ rather than 9/6 because 1.4.11 moved ⚪ → 🟡: its non-text-contrast detector
    // is now registry-backed (formats/xlsx, PARTIAL), so a clean workbook reads REVIEW not "not
    // evaluated". 1.4.1 and 4.1.2 were already 🟡 via the controls-gated review overlay and stay so
    // (now table-backed too). The criterion crosses buckets rather than leaving, so it sums to 20.
    xlsx: { auto: 5, review: 10, human: 0, gap: 0, at: 0, na: 5, certifiable: 5 },
    pptx: { auto: 5, review: 14, human: 1, gap: 0, at: 0, na: 0, certifiable: 5 },
    // pdf is 13🟡/4⚪ rather than 12/5 because 2.4.3 (focus order) moved ⚪ → 🟡: its /Tabs = /S
    // detector is registry-backed now (formats/pdf, HEURISTIC), so it reads REVIEW — a proxy, not a
    // certified pass. 4.1.2 earlier made the same ⚪ → 🟡 move (AcroForm-only, so 🟡 not 🟢). Each
    // criterion crosses buckets rather than leaving, so the estate still sums to 20.
    pdf: { auto: 3, review: 13, human: 0, gap: 0, at: 0, na: 4, certifiable: 3 },  // +1.4.12, +1.4.1, +1.4.11, +2.4.3 (ADR 0025)
    // html is 10🟢/8🟡 rather than 11/7 for the same reason docx moved: 2.4.6 went 🟢→🟡 once
    // HTML_HEADING_SKIP was recognised as a level check, not a descriptiveness one. The
    // criterion CROSSES buckets rather than leaving, so the estate still sums to 20.
    html: { auto: 10, review: 8, human: 0, gap: 0, at: 2, na: 0, certifiable: 10 },
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
    // 5🟢, not 6: docx was the only document format assessing 2.4.6 🟢, so its demotion in
    // 997b7d0 moves the UNION too — the criterion crosses from 🟢 to 🟡 rather than leaving,
    // which is why assessable stays 19 and the total still sums to 20.
    expect(s.auto).toBe(5)
    // Tier A closes the last three union ⚪ (1.4.4 / 1.4.10 / 1.4.12) into the 🟡 review lane.
    expect(s.review).toBe(14)
    expect(s.human).toBe(1)
    expect(s.na).toBe(0)
    expect(s.assessable).toBe(19)
    expect(s.auto + s.review + s.human + s.gap + s.at + s.na).toBe(20)
  })

  it('remediation axis is counted independently (docx: 6⚡ 8🤖 3👤)', () => {
    const s = coverageSummary(filesOf('docx'), { documents: true })
    // Synced to the backend: the v2 capability table had drifted, missing the docx lanes added
    // across #202/#203/#206/#208 (1.4.1/1.4.11 assisted, 2.1.2 human, 4.1.2 auto) — v1 was updated
    // in each, v2 was not, because nothing made it fail. tests/test_capability_frontend_v2_sync.py
    // is now the guard that would. These totals match v1's.
    // remHuman 1→3: batch-2 added 1.4.10 (reflow) and 1.4.12 (text spacing) as HUMAN docx lanes.
    expect({ remAuto: s.remAuto, remAi: s.remAi, remHuman: s.remHuman }).toEqual({ remAuto: 6, remAi: 8, remHuman: 3 })
  })

  it('union prefers the best assessment lane; a distinct remediation resolver is honored', () => {
    // Shown on 1.3.1, not 2.4.6: since 997b7d0 demoted docx 2.4.6 to 🟡 both formats sit in the
    // same lane, so that pair can no longer demonstrate a union PREFERRING one. 1.3.1 still
    // differs (🟢 docx / 🟡 pdf). 2.4.6 keeps the second half — its remediation lane stayed ⚡ on
    // docx while assessment moved, which is exactly the two-axis independence under test.
    expect(statusAcross('1.3.1', ['docx', 'pdf'], assessmentIn)).toBe('auto')   // 🟢 in docx wins
    expect(statusAcross('1.3.1', ['pdf'], assessmentIn)).toBe('review')          // pdf 1.3.1 is 🟡
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

describe('assessmentGaps — the "no assessment method" cells (gap + at), honestly derived', () => {
  // The gap total is exactly the gap + at rollup of coverageSummary, never more: a ⚪ N/A cell is
  // not a gap and a 🔴 human cell is not a missing method. This ties the two derivations together
  // so neither can drift into fabricating a hole.
  for (const fmt of ['docx', 'xlsx', 'pptx', 'pdf', 'html']) {
    it(`.${fmt}: gap total equals coverageSummary's gap + at (${fmt === 'html' ? '2 needs-AT' : 'zero'})`, () => {
      const s = coverageSummary(filesOf(fmt), { documents: true })
      const g = assessmentGaps(filesOf(fmt), { documents: true })
      expect(g.total).toBe(s.gap + s.at)
      expect(g.cells.length).toBe(g.total)
      // every reported cell is genuinely a gap/at lane in the capability table — never invented
      for (const c of g.cells) expect(assessmentIn(c.sc, c.fmt)).toBe(c.lane)
    })
  }

  it('a document-only estate has NO gaps — all statically-detectable document gaps are closed', () => {
    const g = assessmentGaps(filesOf('docx', 'xlsx', 'pptx', 'pdf'), { documents: true })
    expect(g.total).toBe(0)
    expect(g.byFormat).toEqual([])
  })

  it('an .html estate surfaces exactly the two needs-AT keyboard criteria, with AT_REASON', () => {
    const g = assessmentGaps(filesOf('html'), { documents: true })
    expect(g.total).toBe(2)
    expect(g.byFormat).toHaveLength(1)
    expect(g.byFormat[0].fmt).toBe('html')
    expect(g.cells.map((c) => c.sc).sort()).toEqual(['2.1.1', '2.1.2'])
    for (const c of g.cells) {
      expect(c.lane).toBe('at')
      expect(c.reason).toBe(AT_REASON)
    }
  })

  it('a mixed estate groups gaps by format and only lists formats that have them', () => {
    const g = assessmentGaps(filesOf('docx', 'html'), { documents: true })
    expect(g.total).toBe(2)                               // only html contributes
    expect(g.byFormat.map((r) => r.fmt)).toEqual(['html'])
    expect(g.cells.every((c) => c.fmt === 'html')).toBe(true)
  })
})
