// R6 — the manual lane: the work ACP cannot do itself, derived rather than listed.
//
// The capability model has three remediation lanes per (format × criterion): `auto` (deterministic,
// no human), `assisted` (an AI drafts a value, a person approves it) and `human` (nobody can draft
// it — a person opens the document and writes the fix). This module answers one question about a
// scan's findings: WHICH OF THEM ARE IN THE `human` LANE, and on which documents.
//
// THE LANE IS DERIVED, NEVER LISTED. There is no array of "manual criteria" in this file, and there
// must never be one. The answer is `capability.js`'s `modeFor(cap, fmt, sc)` — the table that mirrors
// `api/remediation_capability.py` and is held to it by `tests/test_capability_frontend_sync.py`. A
// hardcoded list is a fourth copy of a fact that already had three disagreeing ones, which is the
// defect `capability.js` exists to have ended.
//
// IT IS FORMAT-AWARE, AND THAT IS THE WHOLE POINT. The lane is a property of the PAIR, not of the
// criterion. 1.4.1 Use of Color is `assisted` on docx, `human` on xlsx and `auto` on html — one
// criterion, three lanes, three different answers to "does a person have to do this?". Two other
// sources in this repo are format-BLIND and must not be mistaken for this one:
//   · `scan_rule_traces.fix_mode` — written from `assessment_policy.RULE_CATALOG`, one value per
//     criterion for every format. It says 2.1.1 Keyboard is 'auto'; the capability table says
//     pptx 2.1.1 is `human`, and the capability table is the one a remediation run obeys.
//   · `remediationTrack.js` — the review workspace's per-item track, also keyed on the criterion
//     alone (via `confidence.methodForSc`), corrected by two hand-maintained override sets.
// Both are right for what they do. Neither can answer "is this manual on THIS document".
//
// TWO WAYS TO BE `human`, AND A READER DESERVES TO KNOW WHICH. `modeFor` returns 'human' both for a
// pair the table explicitly declares human AND for a pair the table does not mention at all — the
// conservative default `capability.js` documents ("A pair absent from a format's map is out of scope
// for that format and treated as human"). Those are not the same statement. The first is an engineering
// judgement that this cannot be automated; the second is silence. `basis` carries the difference so
// the screen can say which one it is rather than presenting a default as a finding.
//
// WHAT THIS DOES NOT COMPUTE: any estimate of how long the manual work takes. The assessment screen
// removed its effort figure — a constant multiplied by a count, rendered to one decimal — and this
// screen does not reintroduce it under a new name. Counting documents and criteria is the whole of
// what the record supports.
import { documentRows } from './assessMetrics.js'
import { modeFor } from './capability.js'
import { PLAIN_NAMES } from './rules/index.js'
import { WCAG } from './wcagCatalog.js'
import { fixSteps, hasGuidance, appName } from './remediationGuide.js'

/** The lane this module selects. Named so a reader of the call site sees which of the three it is. */
export const MANUAL_LANE = 'human'

// WCAG's own name for a criterion — the fallback label, and the only one that covers every criterion.
// `PLAIN_NAMES` is the preferred label (it says what a person would SEE) but it is incomplete: 1.3.2,
// 1.4.8, 2.1.2, 2.4.10 and 3.1.5 have no entry, and four of those five are in the manual lane on at
// least one format. Falling through to the WCAG name is how a real criterion keeps a real label
// instead of rendering as its number alone.
const WCAG_NAME = Object.fromEntries(WCAG.map((w) => [w.sc, w.name]))

/** The label for a criterion: the plain-language phrase where one exists, else WCAG's own name. */
export const labelFor = (sc) => PLAIN_NAMES[sc] || WCAG_NAME[sc] || ''

/**
 * Why this (format, criterion) is in the manual lane.
 *
 *   'declared' — the capability table names this pair `human`. A deliberate statement that the fix
 *                needs a person: `xlsx 4.1.2`, `pdf 2.4.4`, `html 1.1.1`.
 *   'default'  — the table has no entry for this pair, so `modeFor` returns its conservative default.
 *                The record does not say a person is required; it says nothing at all, and this
 *                screen must not upgrade that silence into a claim.
 *
 * Returns null when the pair is not in the manual lane, so a caller can use it as the predicate.
 */
export function manualBasis(cap, fmt, sc) {
  if (modeFor(cap, fmt, sc) !== MANUAL_LANE) return null
  const declared = !!(cap && cap[fmt] && cap[fmt][sc])
  return declared ? 'declared' : 'default'
}

/**
 * The manual lane of one scan, grouped by document.
 *
 * `files` is the same array the assessment screen was given, and the findings are the same findings:
 * this re-cuts that population by lane, it does not re-count the estate. `documentRow` already
 * attaches `fixMode` to every finding from the same `modeFor` call, so the filter here is a read of
 * that value rather than a second derivation of it.
 *
 * Returns null when `files` is not an array — a screen with no scan behind it renders nothing, never
 * a zero. "No documents need manual work" and "we have not been told what the documents are" are
 * different sentences and the second one is not this component's to guess at.
 *
 * @returns {null | {documents: Array, documentCount: number, findingCount: number,
 *                   criteria: string[], defaultedPairs: Array, unopened: Array}}
 */
export function manualWork(files, { cap, assessment, criteria, level = 'AA' } = {}) {
  const rows = documentRows(files, { cap, assessment, ...(criteria ? { criteria } : {}), level })
  if (!rows) return null

  const documents = []
  const criteriaSeen = new Set()
  const defaultedPairs = []
  let findingCount = 0

  // A file the scanner never opened holds no findings — not zero manual findings, NO findings. It
  // travels alongside the lane rather than inside it, so the count above the list stays a count of
  // work that is actually known about. (ADR 0016: a document with no assessment has no findings.)
  const unopened = rows.filter((r) => !r.opened)
      .map((r) => ({ file: r.file, name: r.name, reason: r.reason || '' }))

  for (const row of rows) {
    if (!row.opened) continue
    const manual = (row.findings || []).filter((x) => x.fixMode === MANUAL_LANE)
    if (!manual.length) continue

    const byCriterion = new Map()
    for (const x of manual) {
      if (!byCriterion.has(x.sc)) {
        const basis = manualBasis(cap, row.fmt, x.sc)
        if (basis === 'default') defaultedPairs.push({ file: row.file, fmt: row.fmt, sc: x.sc })
        byCriterion.set(x.sc, {
          sc: x.sc,
          label: labelFor(x.sc),
          basis,
          severity: x.severity,
          findings: [],
          // The manual menu path for this criterion in THIS document's own editor. `fixSteps`
          // always answers — falling back to the app's built-in Accessibility Checker, which is
          // correct for every criterion — and `specific` records whether the answer was the
          // criterion's own path or that fallback, so the screen never dresses the generic
          // instruction up as bespoke guidance.
          steps: fixSteps(x.sc, row.fmt),
          specific: hasGuidance(x.sc),
        })
      }
      byCriterion.get(x.sc).findings.push(x)
      findingCount++
      criteriaSeen.add(x.sc)
    }

    documents.push({
      file: row.file,
      name: row.name,
      fmt: row.fmt,
      app: appName(row.fmt),
      criteria: [...byCriterion.values()]
          .sort((a, b) => a.sc.localeCompare(b.sc, undefined, { numeric: true })),
      findingCount: manual.length,
      // Kept per document so the screen can say, honestly, that finishing the manual work on this
      // file does not finish the file — a run still has to apply the automatic and approved fixes.
      otherLaneFindings: (row.findings || []).length - manual.length,
    })
  }

  // Most manual findings first: this list is a plan for a person's afternoon, and the document that
  // holds the most hand-work is where the afternoon starts. Name breaks ties so the order is stable
  // between two renders of the same scan rather than incidental to the input array.
  documents.sort((a, b) => b.findingCount - a.findingCount || a.name.localeCompare(b.name))

  return {
    documents,
    documentCount: documents.length,
    findingCount,
    criteria: [...criteriaSeen].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })),
    defaultedPairs,
    unopened,
  }
}
