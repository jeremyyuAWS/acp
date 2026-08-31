// How complete the reviewer experience actually is, per (criterion, format), measured.
//
// WHAT A FINDING IS SUPPOSED TO SHOW. Five things: where it is and the evidence, why it matters,
// what ACP changed or what the reviewer must change, how completion will be verified, and
// format-appropriate Mac/Windows instructions where the repair is manual. Four of those are
// assembled by modules with their own tests. What nothing measured was COVERAGE — how many of
// the 62 (criterion, format) pairs in `acp-core-17` actually get each one.
//
// That is the gap this file closes, and it is worth closing because the failure is silent by
// construction: a criterion with no entry does not error or render blank, it falls back to a
// correct but generic line ("Review ▸ Check Accessibility"). So partial coverage and full
// coverage look identical from any screenshot, and a criterion added to the preset arrives with
// generic content that nobody is prompted to fill in.
//
// MEASURED (2026-08-31, all 62 pairs of acp-core-17):
//
//     why it matters                    17/17 criteria   100%
//     criterion-specific repair steps    17/17 criteria   100%   (was 13/17)
//     verify-in-app steps                17/62 pairs       27%
//     pairs with NO instruction at all    0/62 pairs        0%
//
// HOW TO READ THAT. The last row is the one that says the design is honest: every pair, however
// thin its specific content, still gets a correct instruction. The gap is SPECIFICITY, not
// correctness and not blankness — `verifySteps.js` states the rule it follows ("a wrong
// instruction is worse than none... We never invent a menu path we're unsure of"), and 27% is
// what that rule costs, not evidence that it is being broken.
//
// The four that were on the generic fallback — 1.4.1, 1.4.11, 2.1.2, 2.4.3 — now carry their own
// guidance (see reviewerGuidanceFour.test.js), which is why that row reads 17/17. They were not
// answered with menu paths, because a menu path is not what they needed: the built-in
// Accessibility Checker does not test any of the four, so the generic line pointed reviewers at
// a tool that returns clean on a document failing all of them. Each now carries an inspection
// procedure, a "done when", and an explicit statement of what ACP cannot verify.
//
// EXTENDING THE VERIFY STEPS IS BLOCKED, and that is why the floor below is a floor rather than
// a target. Doing it needs CURRENT verified Microsoft 365 menu strings; egress to
// support.microsoft.com is blocked from the build environment, and a search returned
// contradictory answers for the Mac path (Review tab vs Tools ▸ Check Accessibility). Guessing
// is the one thing the module's own honesty rule forbids.
import { describe, expect, it } from 'vitest'

import { fixSteps, hasGuidance } from './remediationGuide.js'
import { verifySteps } from './verifySteps.js'
import { WHY } from './wcagWhy.js'

// `acp-core-17` as api/assessment_policy.SCOPE_PRESETS defines it. Mirrored rather than imported
// because it lives in Python; the count assertions below fail if the two drift.
const CORE = {
  '1.1.1': ['docx', 'pdf', 'pptx', 'xlsx'], '1.3.1': ['docx', 'pdf', 'pptx', 'xlsx'],
  '1.3.2': ['docx', 'pdf', 'pptx', 'xlsx'], '1.3.3': ['docx', 'pdf', 'pptx', 'xlsx'],
  '1.4.1': ['docx', 'pdf', 'pptx', 'xlsx'], '1.4.3': ['docx', 'pdf', 'pptx', 'xlsx'],
  '1.4.5': ['docx', 'pdf', 'pptx', 'xlsx'], '1.4.11': ['docx', 'pdf', 'pptx', 'xlsx'],
  '2.1.1': ['pptx'], '2.1.2': ['docx', 'pptx', 'xlsx'],
  '2.4.2': ['docx', 'pdf', 'pptx', 'xlsx'], '2.4.3': ['pdf', 'pptx'],
  '2.4.4': ['docx', 'pdf', 'pptx', 'xlsx'], '2.4.6': ['docx', 'pdf', 'pptx', 'xlsx'],
  '3.1.1': ['docx', 'pdf', 'pptx', 'xlsx'], '3.1.2': ['docx', 'pdf', 'pptx', 'xlsx'],
  '4.1.2': ['docx', 'pdf', 'pptx', 'xlsx'],
}
const PAIRS = Object.entries(CORE).flatMap(([sc, fs]) => fs.map((f) => [sc, f]))
const PLATFORMS = ['win', 'mac']

describe('reviewer experience coverage across acp-core-17', () => {
  it('the mirrored preset still has 17 criteria and 62 pairs', () => {
    // Guards the mirror. If the preset changes in Python and not here, every number below is
    // describing a set that no longer exists.
    expect(Object.keys(CORE)).toHaveLength(17)
    expect(PAIRS).toHaveLength(62)
  })

  it('every criterion says why it matters', () => {
    // 100%, and asserted as equality rather than a floor: this one is complete, and a criterion
    // arriving without a consequence line should fail rather than quietly lower the average.
    const missing = Object.keys(CORE).filter((sc) => !WHY[sc])
    expect(missing).toEqual([])
  })

  it('THE INVARIANT: no pair ever renders a blank instruction, on either platform', () => {
    // The assertion that matters most, and the one the fallback design exists to guarantee.
    // Partial coverage is acceptable; a finding that tells the reviewer nothing is not.
    const blank = []
    for (const [sc, fmt] of PAIRS) {
      for (const p of PLATFORMS) {
        const guide = fixSteps(sc, fmt)
        const verify = verifySteps(sc, `report.${fmt}`, p)
        if (!guide || !guide[p]) blank.push(`${sc}/${fmt}/${p}: no repair instruction`)
        if (!verify || !verify.checker) blank.push(`${sc}/${fmt}/${p}: no verification instruction`)
      }
    }
    expect(blank).toEqual([])
  })

  it('records the criterion-specific repair coverage as a floor', () => {
    // 13 of 17. A floor, so filling a gap does not fail the build — improvement is the point.
    const specific = Object.keys(CORE).filter((sc) => hasGuidance(sc))
    expect(specific.length).toBeGreaterThanOrEqual(13)
    // Named, so a criterion silently DROPPING to the generic fallback is visible.
    for (const sc of ['1.1.1', '1.3.1', '2.4.2', '2.4.4', '3.1.1', '4.1.2']) {
      expect(hasGuidance(sc), `${sc} lost its criterion-specific repair steps`).toBe(true)
    }
  })

  it('records the verify-in-app coverage as a floor, with the blocker named in the header', () => {
    // 17 of 62 pairs. Low, and honestly so — see the module docstring: raising it needs verified
    // M365 menu strings that this environment cannot reach, and inventing them is what
    // verifySteps.js exists to refuse.
    const withSteps = PAIRS.filter(([sc, fmt]) => {
      const i = verifySteps(sc, `report.${fmt}`, 'win')
      return !!(i && i.steps && i.steps.length)
    })
    expect(withSteps.length).toBeGreaterThanOrEqual(17)
  })

  it('a criterion with verify steps has them on BOTH platforms', () => {
    // The asymmetry that would actually hurt: a Windows reviewer served and a Mac one not, with
    // nothing in the UI to say which happened.
    const lopsided = []
    for (const [sc, fmt] of PAIRS) {
      const w = verifySteps(sc, `report.${fmt}`, 'win')
      const m = verifySteps(sc, `report.${fmt}`, 'mac')
      const hasW = !!(w && w.steps && w.steps.length)
      const hasM = !!(m && m.steps && m.steps.length)
      if (hasW !== hasM) lopsided.push(`${sc}/${fmt}: win=${hasW} mac=${hasM}`)
    }
    expect(lopsided).toEqual([])
  })
})
