// The four criteria a menu path cannot resolve now carry real guidance.
//
// WHY THESE FOUR, AND WHY THE GENERIC LINE WAS WORSE THAN NOTHING. 1.4.1, 1.4.11, 2.1.2 and
// 2.4.3 had no entry in remediationGuide.js and fell through to `genericFor(fmt)` — "Review tab
// > Check Accessibility". That is not merely unspecific. Word, Excel and PowerPoint's built-in
// Accessibility Checker does not test ANY of these four: colour-alone meaning, non-text
// contrast, keyboard traps and focus order are outside what it inspects. So the instruction
// pointed a reviewer at a tool that returns clean on a document failing all four, and a clean
// checker result reads as completion. A generic instruction cannot establish completion here.
//
// WHAT THEY CARRY INSTEAD. An inspection procedure (what to look at and how), plus two fields
// the other criteria do not need:
//
//   completion — how the reviewer knows they are finished
//   limits     — what ACP itself cannot check, so a silent scan is never read as a pass
//
// NO MENU PATHS WERE INVENTED. Every step is something a reviewer does by looking, tabbing or
// measuring, identical on Mac and Windows. Extending the *verified-menu-path* coverage is still
// blocked on current Microsoft 365 strings that this environment cannot reach — and these four
// would not have benefited from one anyway, which is why they were the right four to do first.
import { describe, expect, it } from 'vitest'

import { fixSteps, hasGuidance } from './remediationGuide.js'

const FOUR = ['1.4.1', '1.4.11', '2.1.2', '2.4.3']
const FORMATS = ['docx', 'xlsx', 'pptx', 'pdf']
const CHECKER = /Check Accessibility/

describe('the four criteria a menu path cannot resolve', () => {
  it('all four now have criterion-specific guidance', () => {
    for (const sc of FOUR) expect(hasGuidance(sc), `${sc} is still on the generic fallback`).toBe(true)
  })

  it('THE POINT: none of them is answered with the Accessibility Checker line', () => {
    // The regression. If one of these loses its entry it falls back to the checker line, which
    // reports clean on a document that fails — the exact false-completion this change removes.
    for (const sc of FOUR) {
      for (const fmt of FORMATS) {
        const s = fixSteps(sc, fmt)
        expect(s.win, `${sc}/${fmt} fell back to the Accessibility Checker`).not.toMatch(CHECKER)
        expect(s.mac, `${sc}/${fmt} fell back to the Accessibility Checker`).not.toMatch(CHECKER)
      }
    }
  })

  it('each says what to inspect, what completes it, and what ACP cannot verify', () => {
    for (const sc of FOUR) {
      const s = fixSteps(sc, 'docx')
      expect(s.where.length, `${sc} has no "what to inspect"`).toBeGreaterThan(40)
      expect(s.completion.length, `${sc} has no "done when"`).toBeGreaterThan(40)
      expect(s.limits.length, `${sc} has no "ACP cannot verify"`).toBeGreaterThan(40)
    }
  })

  it('each warns that the built-in checker does not cover it', () => {
    // The reviewer's likeliest wrong move is to run the checker and read clean as done. Every
    // one of the four says so in the step itself, where it will actually be read.
    for (const sc of FOUR) {
      expect(fixSteps(sc, 'docx').win).toMatch(/does NOT test this/)
    }
  })

  it('the limits text names ACP, not the reviewer, as the thing that cannot check it', () => {
    // Guards against these degrading into vague hedges. Each must state the product's own
    // limitation concretely enough to be actionable.
    for (const sc of FOUR) {
      expect(fixSteps(sc, 'docx').limits).toMatch(/ACP/)
    }
  })

  it('2.4.3 is honest that ACP has no order signal on PDF at all', () => {
    // Not a generic caveat: pdf.reading-order is a known open defect that reports nothing on any
    // input, so on PDF specifically there is no partial signal to lean on. If that detector is
    // ever fixed, this line has to change with it.
    expect(fixSteps('2.4.3', 'pdf').limits).toMatch(/1\.3\.2|reading-order/)
  })

  it('every other criterion is untouched and carries no empty new fields', () => {
    // The control. These fields are optional; adding them must not have changed the shape of
    // the 13 entries that were already specific, nor of the generic fallback.
    const specific = fixSteps('1.1.1', 'docx')
    expect(specific.win).toBeTruthy()
    expect(specific.completion).toBe('')
    expect(specific.limits).toBe('')

    const fallback = fixSteps('9.9.9', 'docx')   // no entry at all
    expect(fallback.win).toMatch(CHECKER)
    expect(fallback.completion).toBe('')
    expect(fallback.limits).toBe('')
  })
})
