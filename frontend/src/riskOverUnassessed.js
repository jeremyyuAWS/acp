// A verdict is only as good as the documents behind it.
//
// Two surfaces reached the reassuring answer by counting evidence that was never gathered, and
// both were visible in one screenshot on 2026-08-19, over a 22-document estate where NOTHING had
// been analysed (the SharePoint download bug, #481):
//
//   Remediate hero      "Business risk: Internal content only · overall risk LOW"
//   Drawer status hero  "Ready after 8 reviews · Est. review ~6 min · 12/38 criteria"
//
// The risk line falls through to LOW when `criticalOpen === 0`. Zero findings is what an
// unanalysed estate produces, so absence of evidence was rendered as evidence of absence — and
// "overall risk LOW" is the sentence that gets screenshotted into a status report. The drawer's
// coverage grid and review ETA did the same for one file: a time estimate for reviewing findings
// that do not exist, on a document nobody could open.
//
// Same family as the Review-queue claim fixed in #479 (reviewQueueCopy.js), and as
// `_fill_run_aggregate` in api/store.py, which turned NULL counters into a confident
// "0% audit-ready". A true number, a false conclusion, and the reassuring reading is the wrong one.
//
// THE RULE HERE: a verdict computed over findings is withheld — not softened, not annotated — when
// documents in its population were never assessed. Softening keeps the reader's eye on a verdict
// that has no basis; withholding makes them read the reason instead.
import { statusOf } from './docStatus.js'

/**
 * Documents in this population that produced no assessment — opened and failed ('unanalysable'),
 * or never looked at ('not-assessed', the ADR 0020 Discover-only row).
 *
 * BOTH count, and that is deliberate: for the question "can this verdict be trusted?", a file that
 * failed and a file nobody has opened are the same answer — no findings were gathered from it, so
 * it contributed nothing to the count the verdict rests on.
 */
export function unassessedCount(files) {
  return (files || []).filter((f) => {
    if (!f) return false
    const st = statusOf(f)
    return st === 'unanalysable' || st === 'not-assessed'
  }).length
}

/**
 * Should a findings-derived verdict be shown at all?
 *
 * Only gated when the verdict would be REASSURING. A "3 critical findings open" line is still true
 * with unassessed documents present — findings were genuinely found — and suppressing it would hide
 * a real problem to avoid an imaginary one. It is the clean bill of health that cannot be earned
 * from documents nobody read.
 */
export const canClaimLowRisk = (files) => unassessedCount(files) === 0

/**
 * What the risk line says when the low-risk verdict is withheld. States the number, because
 * "not enough information" without a quantity is the kind of caveat readers skip.
 */
export function unassessedRiskText(files) {
  const n = unassessedCount(files)
  return `Risk not assessed — ${n} document${n === 1 ? '' : 's'} produced no assessment, `
    + 'so there is no basis for a risk verdict.'
}

/**
 * Should the drawer's coverage + review-estimate hero render for this file?
 *
 * False for a document that was never assessed. The hero is "the FIRST thing a reviewer reads on a
 * file" (ADR 0026) — for a file that failed, the first thing should be why, which the findings
 * section now states from the record (#483).
 */
export function showsAssessmentHero(file) {
  if (!file) return false
  const st = statusOf(file)
  return st !== 'unanalysable' && st !== 'not-assessed'
}
