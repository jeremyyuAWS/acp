// The one definition of "what is this document's compliance verdict".
//
// It lived in FileDrawer.jsx, and because that module drags in the whole drawer (api.js,
// EvidenceCard, PagePreview, …) every other consumer either imported the heavy drawer or
// re-typed the rule — scanReport.js carries a comment saying exactly that. Two copies of a
// verdict is how the dashboard came to disagree with itself, so the rule lives here, in a
// module with no dependencies, and FileDrawer re-exports it for its existing importers.
//
// Mirrors api/report.py `_status` so the app, the certification PDF and the dashboards can
// never classify the same file differently.
//
// 'issues' means OPEN FINDINGS. A not-certifiable file with ZERO findings is 'clean', not
// 'issues' — nothing about it needs remediating.
//
// CLEAN IS NEVER INFERRED FROM MISSING DATA. 'clean' is an affirmative claim: this document was
// opened, every criterion ACP has a method for ran against it, and none failed. A document with
// NO SCORE was not measured, so it cannot support that claim — it gets 'not-assessed', its own
// state, and the UI says so instead of reassuring anybody.
//
// The distinction is the product. On 2026-07-30 two Drive spreadsheets rendered
// "status: clean · score: n/a · findings: clean" in the file inventory while the drawer for one
// of them, reading the same scan's rule traces, reported "1 issue needs remediation". Both rows
// had a null score: nobody had scored them, and the fall-through called that clean. A false
// "clean" on a compliance product tells a customer they are certifiable when no one checked,
// which is strictly worse than a visible gap.
//
// A null score is a reliable marker of "not measured" rather than a proxy for one: rubric.assess
// returns `score = None` if and only if it returns Status.ERROR, so every ANALYSED or UNCERTAIN
// record carries a number. A row with no score is therefore an ADR 0020 Discover-only inventory
// row, a shadow-skip record, or a row written by a path that never assessed the file — never a
// document that was assessed and scored nothing.
//
// Ordering matters: 'error' and 'uncertain' are checked FIRST, so a file that was opened and
// failed to analyse keeps reporting 'unanalysable'/'uncertain' (both also have no score) rather
// than being demoted to "nobody looked".
//
// Mirrors api/report.py `_status` so the app, the certification PDF and the dashboards can
// never classify the same file differently.
export const NOT_ASSESSED = 'not-assessed'
export const statusOf = (f) => (
  f.status === 'error' ? 'unanalysable'
  : f.status === 'uncertain' ? 'uncertain'
  : f.compliant ? 'certifiable'
  : (f.issues && f.issues.length) ? 'issues'
  : f.score == null ? NOT_ASSESSED
  : 'clean'
)

// Every verdict a document can carry, in reporting order — statusOf returns exactly these and
// nothing else, which is what lets statusCounts below seed all its buckets. Any aggregate over
// files must cover ALL of them: the counter that only knew four is how "2 issues" came to sit
// above two rows that both said clean (Dashboard's hero derived its amber bucket by subtracting
// the other three from the total, so anything it had no bucket for landed in "issues").
export const ALL_STATUSES = ['certifiable', 'issues', 'clean', NOT_ASSESSED, 'uncertain', 'unanalysable']

// Badge palette + caption for a verdict. Canonical here, beside statusOf, because a fourth
// hand-copied colour map is how the inventory row and the drawer badge came to disagree about
// the same file. FileDrawer re-exports both for its existing importers.
//
// 'not-assessed' is deliberately NOT the reassuring blue 'clean' wears — a reviewer scanning
// the inventory must be able to see at a glance that a row is a gap, not a pass.
export const STATUS_BADGE = {
  certifiable: ['var(--success-bg)', 'var(--success-fg)'], issues: ['var(--warn-bg)', 'var(--warn-fg)'],
  uncertain: ['#E6EFFB', '#2A5E9E'], unanalysable: ['#EEEDEA', '#5F5E5A'],
  clean: ['#E8F0FB', '#2A5E9E'], [NOT_ASSESSED]: ['#EEEDFE', '#3C3489'],
}
// Badge caption per status — the raw key reads badly for these two.
export const STATUS_TAG_LABEL = { clean: 'no findings', [NOT_ASSESSED]: 'not assessed' }

// A document nobody scored — no score, no findings, no verdict to report. Distinguishing it
// matters for any RATE: "0% audit-ready" over documents nobody analysed is not a measurement,
// it is a blank denominator wearing a percentage sign.
//
// Derived from statusOf rather than re-testing `status === 'discovered'`, which was too narrow:
// the ADR 0020 fallback is one way to get an unscored row, not the only one, and the estate's
// "how much did we analyse" figure counted the others as analysed.
export const isUnassessed = (f) => statusOf(f) === NOT_ASSESSED
export const analysedCount = (files) => (files || []).filter((f) => !isUnassessed(f)).length

// Count files into the five verdicts — every bucket present, zeros included. COUNT, NEVER
// SUBTRACT: a bucket derived as "total minus the ones I named" silently absorbs every state the
// caller forgot, and reports it as the state it did name.
export const statusCounts = (files) => {
  const c = Object.fromEntries(ALL_STATUSES.map((s) => [s, 0]))
  ;(files || []).forEach((f) => { c[statusOf(f)] += 1 })
  return c
}

// The mean of the scores that EXIST, or null when the group holds none.
//
// null, not 0, for the same reason auditReady is null above: 0/100 is a measurement — it says
// every document was checked and every one scored zero — and a group of unopened inventory rows
// has not been checked at all. Overview carried its own copy of this that returned 0, so a
// cancelled 258-document scan rendered "Finance 0", "Human Resources 0" down the whole
// "Average score by department" panel, asserting an estate-wide failure nobody had measured.
//
// Two copies of an aggregate is how the dashboard came to disagree with itself before; both
// call sites (Overview's panels, scanReport's PDF rollups) now read this one.
export const avgScore = (files) => {
  const scored = (files || []).filter((f) => f.score != null)
  return scored.length ? Math.round(scored.reduce((a, f) => a + f.score, 0) / scored.length) : null
}
