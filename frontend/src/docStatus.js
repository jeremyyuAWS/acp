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
// 'issues' — it is either an unscored Discover/skip record (ADR 0020: listed, never opened)
// or a file that was assessed and failed no rule. Neither has anything to remediate.
export const statusOf = (f) => (
  f.status === 'error' ? 'unanalysable'
  : f.status === 'uncertain' ? 'uncertain'
  : f.compliant ? 'certifiable'
  : (f.issues && f.issues.length) ? 'issues'
  : 'clean'
)

// A Discover-only inventory row (api/store.py get_scan's ADR 0020 fallback) — listed from the
// source's metadata, never opened, so it has no score, no findings and no verdict to report.
// Distinguishing it matters for any RATE: "0% audit-ready" over documents nobody analysed is
// not a measurement, it is a blank denominator wearing a percentage sign.
export const isUnassessed = (f) => f.status === 'discovered'
export const analysedCount = (files) => (files || []).filter((f) => !isUnassessed(f)).length
