import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { statusOf, findingsClaim, STATUS_BADGE, STATUS_TAG_LABEL } from './FileDrawer.jsx'
import { isUnassessed, analysedCount, ALL_STATUSES, NOT_ASSESSED } from './docStatus.js'

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'FileDrawer.jsx'), 'utf8')

describe('FileDrawer renders a clean file honestly (no self-contradiction)', () => {
  it('journey marks Remediate not-needed (skip), never in-progress, for a clean file', () => {
    expect(src).toMatch(/if \(st === 'clean'\) return \[\.\.\.base, 'skip'/)
  })
  it('score line shows the claim instead of a bare n/a when there is no score', () => {
    // Gated on the absence of a SCORE, not on the verdict — `st === 'clean' && score === null`
    // is now unreachable, and an unscored file fell through it to render "n/a / 100".
    expect(src).toMatch(/\{file\.score == null\s*\n\s*\? <span className="drawerscore">/)
    expect(src).toMatch(/no findings/)
    // The JSX form specifically — anchored on the opening brace so prose about the old shape
    // does not trip it.
    expect(src).not.toMatch(/\{st === 'clean' && file\.score === null/)
  })
  it('suppresses the remediation action when there are no findings', () => {
    // The remediation action now lives INSIDE the status hero as its `actionSlot` (the merge that
    // removed the separate "Auto-remediate" card). The no-findings suppression moved with it: the
    // slot builder returns null on an empty findings list, so a clean file shows no remediate CTA.
    expect(src).toMatch(/actionSlot=\{\(\(\) =>/)
    expect(src).toMatch(/if \(!scanId \|\| !r \|\| issues\.length === 0/)
  })
})

// A file's verdict must key 'issues' on ACTUAL findings — not merely on `compliant` being
// false — and must key 'clean' on an actual MEASUREMENT, not on the absence of one.
describe('statusOf — clean vs issues', () => {
  it('classifies a SCORED, not-certifiable, zero-finding file as clean (not issues)', () => {
    // Scored is the operative word: these were opened and failed no rule, so 'clean' is a claim
    // the data supports. Every case here carries a number.
    expect(statusOf({ status: 'analysed', compliant: 0, issues: [], score: 100 })).toBe('clean')
    expect(statusOf({ status: 'analysed', compliant: 0, score: 92 })).toBe('clean') // undefined issues
    expect(statusOf({ status: 'analysed', compliant: 0, issues: [], score: 0 })).toBe('clean') // 0 is a score
  })

  it('classifies a file WITH findings as issues', () => {
    expect(statusOf({ status: 'analysed', compliant: 0, issues: [{ wcag: '1.1.1' }], score: 55 })).toBe('issues')
  })

  it('keeps the existing verdicts intact', () => {
    expect(statusOf({ status: 'analysed', compliant: 1, issues: [], score: 100 })).toBe('certifiable')
    expect(statusOf({ status: 'analysed', compliant: 1, issues: [{ wcag: '1.1.1' }], score: 90 })).toBe('certifiable')
    expect(statusOf({ status: 'error', compliant: 0, issues: [] })).toBe('unanalysable')
    expect(statusOf({ status: 'uncertain', compliant: 0, issues: [] })).toBe('uncertain')
  })

  it('has a badge colour for every verdict, so no list view can crash on one', () => {
    for (const st of ALL_STATUSES) {
      expect(STATUS_BADGE[st], `no badge colour for '${st}'`).toBeTruthy()
      expect(STATUS_BADGE[st]).toHaveLength(2)
    }
  })
})

// ── THE RULE: "clean" is never inferred from missing data ────────────────────────────────────
//
// Reported live 2026-07-30 on v2026.7.29.8 (commit 9dc2ac4), a build that already contained #84
// and #86. Two Google Drive spreadsheets in the file inventory:
//
//     acme-fy2026-summary.xlsx                          status: clean  score: n/a  findings: clean
//     assessment-applicability-matrix-28JUL-Final.xlsx   status: clean  score: n/a  findings: clean
//
// while the drawer for the FIRST of those, at the same moment, read "🔴 1 issue needs
// remediation · 1 criterion is failing and needs a fix". Both rows had a null score: nothing had
// been scored, and the verdict's final fall-through called that "clean".
//
// A null score is a sound marker for "not measured" rather than a guess at one: rubric.assess
// (scripts/rubric.py) returns score=None if and only if it returns Status.ERROR, so every
// ANALYSED or UNCERTAIN record carries a number. No scored file can reach these assertions.
describe('a document nobody scored is not a document without problems', () => {
  it('does NOT render an unscored file as clean, on any path that produces one', () => {
    for (const f of [
      { status: 'discovered', compliant: 0, issues: [], score: null },  // ADR 0020 inventory row
      { status: 'skipped', compliant: 0, issues: [], score: null },     // shadow-skip record
      { status: 'analysed', compliant: 0, issues: [], score: null },    // saved without a score
      { status: 'analysed', compliant: 0, issues: [] },                 // score absent entirely
    ]) {
      expect(statusOf(f), `${f.status} w/ score ${f.score} still reads as clean`).not.toBe('clean')
      expect(statusOf(f)).toBe(NOT_ASSESSED)
      expect(isUnassessed(f)).toBe(true)
    }
  })

  it('never captions an unscored file with an affirmative findings claim', () => {
    // The badge caption is what the customer actually reads. 'clean' renders "no findings";
    // whatever the unscored state renders, it must not be a claim that there are none.
    expect(STATUS_TAG_LABEL.clean).toBe('no findings')
    expect(STATUS_TAG_LABEL[NOT_ASSESSED]).toBe('not assessed')
    expect(STATUS_TAG_LABEL[NOT_ASSESSED]).not.toMatch(/no findings|clean|clear|pass/i)
  })

  it('gives the unscored state its own badge, not the reassuring one clean wears', () => {
    expect(STATUS_BADGE[NOT_ASSESSED]).not.toEqual(STATUS_BADGE.clean)
    expect(STATUS_BADGE[NOT_ASSESSED]).not.toEqual(STATUS_BADGE.certifiable)
  })

  it('still reports a file that was OPENED and failed to analyse as such, not as unmeasured', () => {
    // 'error' and 'uncertain' records also carry no score. They were opened — demoting them to
    // "nobody looked" would lose the fact that ACP tried and the document defeated it.
    expect(statusOf({ status: 'error', compliant: 0, issues: [], score: null })).toBe('unanalysable')
    expect(statusOf({ status: 'uncertain', compliant: 0, issues: [], score: null })).toBe('uncertain')
    expect(isUnassessed({ status: 'error', score: null })).toBe(false)
  })

  it('does not count an unscored document as analysed', () => {
    const files = [
      { status: 'discovered', compliant: 0, issues: [], score: null },
      { status: 'analysed', compliant: 0, issues: [], score: null },   // was counted as analysed
      { status: 'analysed', compliant: 1, issues: [], score: 100 },
    ]
    expect(analysedCount(files)).toBe(1)
  })
})

// The inventory row and the drawer are two different renderings of one fact. They may only
// disagree by ONE of them declining to answer — never by asserting opposite answers.
describe('the inventory row and the drawer cannot disagree about a file having findings', () => {
  // The exact live pair: the row's verdict, and the server status model the drawer's hero reads.
  const unscored = { file: 'acme-fy2026-summary.xlsx', status: 'discovered', compliant: 0, issues: [], score: null }
  const FAILING = { available: true, needs_remediation: 1, in_scope: 38, resolved: 5 }

  it('never lets the row claim "no findings" while the server reports one failing', () => {
    const st = statusOf(unscored)
    const claim = findingsClaim(st, unscored, FAILING)

    // The row does not assert clean...
    expect(st).toBe(NOT_ASSESSED)
    expect(STATUS_TAG_LABEL[st]).not.toMatch(/no findings/i)
    // ...and the drawer, holding the server model, states the finding rather than the row's
    // silence. This is the reconciliation #84 built; it has to keep running for the unscored
    // verdict, which is the one the server has something to add about.
    expect(claim).toBe('has-findings')
    expect(claim).not.toBe('no-findings')
  })

  it('agrees across the whole cross-product of verdict and server model', () => {
    const files = {
      unscored,
      scoredClean: { status: 'analysed', compliant: 0, issues: [], score: 100 },
      withIssues: { status: 'analysed', compliant: 0, issues: [{ wcag: '1.1.1' }], score: 55 },
    }
    const models = {
      failing: FAILING,
      clear: { available: true, needs_remediation: 0 },
      absent: { available: false },
      none: null,
    }
    for (const [fname, f] of Object.entries(files)) {
      for (const [mname, m] of Object.entries(models)) {
        const st = statusOf(f)
        const claim = findingsClaim(st, f, m)
        const rowSaysNoFindings = st === 'clean' || st === 'certifiable'
        const serverSaysFindings = m?.available !== false && m?.needs_remediation > 0
        // The one forbidden combination: the row reassuring while the server contradicts it.
        expect(rowSaysNoFindings && serverSaysFindings && claim === 'no-findings',
          `${fname} + ${mname}: row says clear, server says failing, claim says clear`).toBe(false)
        // And never an affirmative "no findings" about a file that was never scored.
        if (st === NOT_ASSESSED) expect(claim).not.toBe('no-findings')
      }
    }
  })
})
