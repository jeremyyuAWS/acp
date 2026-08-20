// The seven numbers the Assess results screen is allowed to show, and nothing else.
//
// This module is the code half of the metric-definition table agreed for the redesign. The rule it
// exists to enforce is not "compute some totals" — it is that EVERY number on that screen has one
// definition, one unit and one denominator, written down once, here.
//
// WHY A MODULE RATHER THAN A COMPONENT. The screen it replaces led with four counts of "problems"
// — 112 findings, 13 issues needing remediation, 189 unresolved, 5/20 fully assessed — each over a
// different denominator, none of them stated. Every one was individually correct. Read together
// they said the estate had 112, or 13, or 189 problems, in 4 documents or 22, out of 16 criteria or
// 20 or 836. Putting the arithmetic in one place is what stops a fifth denominator arriving with
// the next panel.
//
// THE UNITS, and they are not interchangeable:
//   · document — one file that was opened and scored.
//   · criterion — one WCAG success criterion in the agreed scope.
//   · check — one criterion judged against one document. documents × criteria.
//   · finding — one concrete instance inside a document. A failing check can hold many.
// "Issue" is not a unit and does not appear in this file. It was previously used for all three of
// findings, failing checks and unresolved checks, on one screen.
//
// WHAT THIS DELIBERATELY DOES NOT COMPUTE: an accessibility score, any percentage, and any estimate
// of human effort. The score has no documented weighting and can read "good" while a critical
// finding is open; the effort figure was a constant multiplied by a count and rendered to one
// decimal place. Both were removed rather than rewritten, and neither returns without the evidence
// named in the agreed table.
import { fmtOf, modeFor, assessmentFor } from './capability.js'
import { scOfWcag } from './coreStats.js'
import { findingLevel, RANK } from './findingLevel.js'
import { SCOPE_SCS, SCOPE_LABEL } from './activeScope.js'

/** The four severities the engine emits, in the order the screen shows them. */
export const SEVERITIES = ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR']
export const SEVERITY_LABEL = { CRITICAL: 'critical', SERIOUS: 'serious', MODERATE: 'moderate', MINOR: 'minor' }

// A file the scanner could not read. `status` is the backend's own value — 'analysed' / 'uncertain'
// / 'error' — and only 'error' means no check ever ran against it.
const isUnopened = (f) => f && f.status === 'error'

// Unresolved is the default, not an assumption: a finding carries a resolution only once somebody
// has acted on it. Written this way so the metric starts falling the moment the backend begins
// sending the field, rather than needing a second change here.
const isUnresolved = (x) => !x || !x.resolution || x.resolution === 'none'

/**
 * Whether ACP could judge this criterion for this format at all.
 *
 * The assessment lane is 'auto' (ACP certifies), 'review' (ACP finds evidence, a person decides),
 * 'human' (a person assesses it end to end) or null (the pair is out of scope for the format).
 * Only the first two are a check that RAN. The last two are the "unable to assess" bucket — and
 * they are neither passes nor failures, which is the distinction the previous screen lost.
 */
const laneRan = (lane) => lane === 'auto' || lane === 'review'

/**
 * Every metric on the results screen, from one pass over the estate.
 *
 * Returns `null` when there is nothing to reason about — no file list yet, or a failed read. The
 * caller renders NOTHING on null. It must not render zeros: "0 findings" is a completed run that
 * found none, and a run that has not happened is not that. This distinction has been the source of
 * repeated defects in this codebase and is the reason for the null.
 *
 * @param files       the scan's file rows, each `{status, name, issues:[{wcag, severity, ...}]}`
 * @param cap         remediation-capability map {fmt:{sc:'auto'|'assisted'|'human'}}
 * @param assessment  assessment-lane map {fmt:{sc:'auto'|'review'|'human'}}
 * @param criteria    the agreed criteria the counts are taken over (defaults to the agreed scope)
 * @param level       conformance target; findings above it do not block and are not counted
 * @param notStarted  documents selected but never begun — only the caller knows this, and it is
 *                    what separates a partial run from a complete one. Omit when unknown; passing
 *                    0 asserts that every selected document was started.
 */
/**
 * One document's numbers — the single per-file pass the whole screen reads.
 *
 * Extracted rather than duplicated because THREE views need it: the estate summary sums these, the
 * worklist renders one per row, and the per-file view groups this document's findings by criterion.
 * Three modules answering "how many findings does this file have" independently is exactly the
 * drift that produced four different answers on the screen this replaces.
 *
 * An unopened file gets a row too, with `opened: false` and NO counts — the caller decides whether
 * to show it and cannot accidentally read a zero off it, because there is no number there to read.
 * Findings, checks and criteria are scoped and level-filtered here, once.
 */
export function documentRow(f, { cap, assessment, criteria = SCOPE_SCS, level = 'AA' } = {}) {
  if (!f) return null
  const name = f.name || f.file || ''
  if (isUnopened(f)) {
    return { file: f.file || name, name, fmt: fmtOf(f), opened: false,
             reason: f.error || f.reason || '', state: 'unopened' }
  }

  const target = RANK[level] || RANK.AA
  const fmt = fmtOf(f)

  let checksEvaluated = 0, checksUnable = 0, anyReviewLane = false
  const criteriaEvaluated = new Set(), criteriaUnable = []
  for (const sc of criteria) {
    const lane = assessmentFor(assessment, fmt, sc)
    if (laneRan(lane)) {
      checksEvaluated++
      criteriaEvaluated.add(sc)
      if (lane === 'review') anyReviewLane = true
    } else {
      checksUnable++
      criteriaUnable.push(sc)
    }
  }

  const bySeverity = { CRITICAL: 0, SERIOUS: 0, MODERATE: 0, MINOR: 0, UNKNOWN: 0 }
  const findings = []
  let autoFix = 0
  for (const x of f.issues || []) {
    if (!isUnresolved(x)) continue
    const sc = scOfWcag(x.wcag)
    if (!sc || !criteria.has(sc)) continue
    if (RANK[findingLevel(x)] > target) continue
    const sev = SEVERITIES.includes(x.severity) ? x.severity : 'UNKNOWN'
    // Deterministic ONLY. 'assisted' is an AI draft awaiting a person's approval — counting it as
    // automation is what produced "51% auto-remediable" for work nobody could apply unattended.
    const auto = modeFor(cap, fmt, sc) === 'auto'
    if (auto) autoFix++
    bySeverity[sev]++
    findings.push({ ...x, sc, severity: sev, level: findingLevel(x), auto,
                    fixMode: modeFor(cap, fmt, sc) })
  }

  // The severity mix of the findings a PERSON has to deal with, separately from the mix
  // overall. The ordering rests on this: ten auto-fixable criticals cost nobody an afternoon.
  const bySeverityHuman = { CRITICAL: 0, SERIOUS: 0, MODERATE: 0, MINOR: 0, UNKNOWN: 0 }
  for (const x of findings) if (!x.auto) bySeverityHuman[x.severity]++

  return {
    file: f.file || name, name, fmt, opened: true,
    findings, totalFindings: findings.length, bySeverity, bySeverityHuman,
    autoFixAvailable: autoFix, humanReviewRequired: findings.length - autoFix,
    // Does this document need a person at all? A row where everything is deterministic is real
    // work for the machine and none for the reader, and the worklist says so rather than making
    // them open it to find out.
    needsPerson: findings.length - autoFix > 0,
    criteriaFailing: [...new Set(findings.map((x) => x.sc))].sort(),
    criteriaEvaluated: [...criteriaEvaluated].sort(),
    unassessableCriteria: criteriaUnable.sort(),
    checksEvaluated, unableToAssess: checksUnable, selectedChecks: checksEvaluated + checksUnable,
    anyReviewLane,
    // Per document, the same precedence the estate status uses. "Clear" here means nothing failed,
    // never that the document conforms — the unassessable count travels with it for that reason.
    state: findings.length ? 'attention' : anyReviewLane ? 'awaiting_review' : 'clear',
  }
}

// Triage ordering only. A per-rule severity scale summed into one per-document figure is the score
// defect in miniature, so this weight orders rows and is never rendered as a number.
const SORT_WEIGHT = { CRITICAL: 1000, SERIOUS: 100, MODERATE: 10, MINOR: 1, UNKNOWN: 1 }

const weigh = (mix) => SEVERITIES.reduce((a, s) => a + mix[s] * SORT_WEIGHT[s], 0)
                       + mix.UNKNOWN * SORT_WEIGHT.UNKNOWN

/**
 * The worklist: one row per document, ordered by what needs a PERSON.
 *
 * Three keys, in this order:
 *
 *   1. the severity mix of findings needing a person — the only genuinely scarce resource here;
 *   2. the severity mix overall, so two documents that need equal attention order sensibly;
 *   3. the name, so the order is stable rather than incidental.
 *
 * This is deliberately not "worst first". A document holding ten auto-fixable critical findings
 * ranks BELOW one holding a single serious finding that needs judgement, because after remediation
 * runs the first document is clean and the second still needs somebody. Nothing is hidden by this:
 * an auto-fixable critical is still shown, still red, and still counted in every total — it simply
 * stops occupying the top of a list of things to do.
 *
 * Unopened files sort last. They hold no work at all, and putting them first would make the very
 * first row the one thing a reader cannot act on.
 */
export function documentRows(files, opts = {}) {
  if (!Array.isArray(files)) return null
  const rows = files.map((f) => documentRow(f, opts)).filter(Boolean)
  return rows.sort((a, b) => {
    if (!a.opened || !b.opened) return (a.opened ? 0 : 1) - (b.opened ? 0 : 1)
    return weigh(b.bySeverityHuman) - weigh(a.bySeverityHuman)
        || weigh(b.bySeverity) - weigh(a.bySeverity)
        || a.name.localeCompare(b.name)
  })
}

/**
 * One document's findings, grouped by WCAG success criterion.
 *
 * Grouping happens INSIDE a file, never as the top-level worklist: remediation happens to
 * documents, so a rule-first worklist would ask one person to open the same document five times.
 * Within a file, the grouping is what tells the fixer what kind of work the next twenty minutes is.
 *
 * Ordered by what needs a PERSON first, then by worst severity, then by criterion number so two
 * equally placed groups order stably. Same reason as the worklist: a criterion ACP fixes
 * deterministically is one button in remediation, so it belongs below the ones somebody has to
 * think about — even when it is the more severe of the two.
 */
export function findingsByCriterion(row) {
  if (!row || !row.opened) return null
  const by = new Map()
  for (const x of row.findings) {
    if (!by.has(x.sc)) {
      by.set(x.sc, { sc: x.sc, findings: [], autoFixAvailable: 0, humanReviewRequired: 0 })
    }
    const g = by.get(x.sc)
    g.findings.push(x)
    if (x.auto) g.autoFixAvailable++
    else g.humanReviewRequired++
  }
  const worst = (g) => Math.min(...g.findings.map((x) => {
    const i = SEVERITIES.indexOf(x.severity)
    return i < 0 ? SEVERITIES.length : i
  }))
  return [...by.values()]
    .map((g) => ({ ...g, severity: SEVERITIES[worst(g)] || 'UNKNOWN', level: g.findings[0].level,
                   needsPerson: g.humanReviewRequired > 0 }))
    .sort((a, b) => (b.needsPerson ? 1 : 0) - (a.needsPerson ? 1 : 0)
                 || worst(a) - worst(b)
                 || a.sc.localeCompare(b.sc, undefined, { numeric: true }))
}

export function assessMetrics(files, { cap, assessment, criteria = SCOPE_SCS, level = 'AA', notStarted } = {}) {
  if (!Array.isArray(files)) return null

  const rows = documentRows(files, { cap, assessment, criteria, level })
  const assessed = rows.filter((r) => r.opened)
  const unopened = rows.filter((r) => !r.opened)

  let totalFindings = 0
  let autoFix = 0
  const bySeverity = { CRITICAL: 0, SERIOUS: 0, MODERATE: 0, MINOR: 0, UNKNOWN: 0 }
  const attention = new Set()

  // Checks: one criterion against one document. Summed over ASSESSED documents only — a file that
  // was never opened has no checks, and including it would inflate the denominator of every
  // coverage number on the screen.
  let checksEvaluated = 0
  let checksUnable = 0
  const criteriaEvaluated = new Set()
  const criteriaUnable = new Set()
  let anyReviewLane = false

  for (const r of assessed) {
    checksEvaluated += r.checksEvaluated
    checksUnable += r.unableToAssess
    r.criteriaEvaluated.forEach((sc) => criteriaEvaluated.add(sc))
    r.unassessableCriteria.forEach((sc) => criteriaUnable.add(sc))
    if (r.anyReviewLane) anyReviewLane = true

    totalFindings += r.totalFindings
    autoFix += r.autoFixAvailable
    for (const s of SEVERITIES) bySeverity[s] += r.bySeverity[s]
    bySeverity.UNKNOWN += r.bySeverity.UNKNOWN
    if (r.totalFindings) attention.add(r.file)
  }

  // A criterion evaluated in ANY assessed document counts as covered; one that ran nowhere does
  // not. Reported as "14 of 17", never as a percentage — the percentage hides which three.
  const coverageEvaluated = criteriaEvaluated.size

  return {
    // ── documents ──────────────────────────────────────────────────────────────────────────
    documentsSelected: files.length,
    documentsAssessed: assessed.length,
    documentsNeedingAttention: attention.size,
    // Named, not just counted: a file ACP could not open is excluded from every other number on
    // the screen, so the screen has to say which and why.
    documentsUnopened: unopened.map((r) => ({ file: r.file, name: r.name, reason: r.reason })),
    // The worklist, already ordered. Handed out rather than recomputed by the caller, so the
    // summary's totals and the rows beneath it can never come from two different passes.
    rows,

    // ── findings ───────────────────────────────────────────────────────────────────────────
    totalFindings,
    bySeverity,
    autoFixAvailable: autoFix,
    humanReviewRequired: totalFindings - autoFix,

    // ── checks ─────────────────────────────────────────────────────────────────────────────
    selectedChecks: checksEvaluated + checksUnable,
    checksEvaluated,
    unableToAssess: checksUnable,
    unassessableCriteria: [...criteriaUnable].sort(),

    // ── coverage, stated as a fraction of a named list ──────────────────────────────────────
    coverageEvaluated,
    coverageSelected: criteria.size,
    scopeLabel: criteria === SCOPE_SCS ? SCOPE_LABEL : 'document core',

    status: statusOf({
      selected: files.length, assessed: assessed.length, notStarted,
      findings: totalFindings, anyReviewLane,
    }),
  }
}

/**
 * Which of the seven screen states this run is in.
 *
 * Evaluated in precedence order, first match wins, so a failed run can never present as clear and a
 * partial run can never present as complete. That ordering is the whole point: the two states the
 * previous screen could not express were "partial" and "some checks never ran", and both rendered
 * as an ordinary completed result.
 *
 * `partial` requires knowing how many selected documents were never started, which the file list
 * alone cannot say — so it is reported only when the caller supplies `notStarted`. Absent that,
 * this returns the completed state it can defend rather than guessing at one it cannot.
 */
export function statusOf({ selected, assessed, notStarted, findings, anyReviewLane }) {
  if (!selected) return 'empty'                        // nothing matched the scope
  if (!assessed) return 'failed'                       // no check reached a terminal state
  if (notStarted > 0) return 'partial'                 // some selected document never began
  if (findings > 0) return 'attention'
  if (anyReviewLane) return 'awaiting_review'          // nothing failed, but a person still decides
  return 'clear'
}

export const STATUS_LABEL = {
  empty: 'Nothing to assess',
  failed: 'Assessment could not run',
  partial: 'Partially completed',
  attention: 'Needs attention',
  awaiting_review: 'Awaiting review',
  clear: 'No findings',
}

/**
 * The sentence that goes wherever a status is shown.
 *
 * "Clear" never travels alone. Where any selected check could not run, the coverage fraction sits
 * beside it — this screen gets screenshotted, and a bare "no findings" over a run that evaluated 14
 * of 17 criteria is the most damaging thing the product could print.
 */
export function coverageSentence(m) {
  if (!m) return null
  return `${m.coverageEvaluated} of ${m.coverageSelected} selected criteria evaluated`
}

/**
 * Does the screen's arithmetic hold?
 *
 * Rendered, not merely asserted in a test: a partition that stops summing is then visible to the
 * reader rather than only to whoever reads the query. Returns the two identities the results screen
 * prints under the summary.
 */
export function reconcile(m) {
  if (!m) return null
  const sevSum = SEVERITIES.reduce((a, s) => a + m.bySeverity[s], 0) + m.bySeverity.UNKNOWN
  return {
    findings: {
      ok: m.autoFixAvailable + m.humanReviewRequired === m.totalFindings && sevSum === m.totalFindings,
      line: `${m.autoFixAvailable} auto-fixable + ${m.humanReviewRequired} needing review = ${m.totalFindings} findings`,
    },
    checks: {
      ok: m.checksEvaluated + m.unableToAssess === m.selectedChecks,
      line: `${m.checksEvaluated} checks evaluated + ${m.unableToAssess} unable to assess = `
            + `${m.selectedChecks} selected checks (${m.documentsAssessed} documents × ${m.coverageSelected} criteria)`,
    },
  }
}
