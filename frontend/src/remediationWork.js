// The remediation partition: the SAME findings the assessment counted, split by WHO does the work.
//
// The assessment screen partitions findings by SEVERITY — a property of the emitting rule, useful
// for triage order and useless for planning. This module partitions the identical population by the
// only question remediation actually turns on: who has to be in the room for this finding to go
// away. Five answers, one per finding, no finding in two of them:
//
//   automatic   ACP applies it. Deterministic — same input, same output, no model call.
//   drafted     an AI wrote a candidate value; a PERSON approves it before anything is written.
//   authored    nobody can draft it. ACP shows the location and a person writes the fix.
//   applied     a remediation run has already produced a corrected copy carrying this fix.
//   unfixable   this run reported that it cannot be fixed here at all.
//
// THE ONE RULE THIS MODULE EXISTS TO ENFORCE. `auto` means deterministic and nothing else. An AI
// draft is advice awaiting approval; it is not automation and it never counts as automation.
// Folding `assisted` into `auto` is exactly what produced "51% auto-remediable" for work nobody
// could apply unattended, and it is a one-character change away at all times — which is why
// `laneOfFinding` reads `fixMode` against three named literals rather than testing "not human".
//
// WHY IT SUMS, AND WHY THE SUM IS RENDERED. `reconcileWork` returns the identity line the panel
// prints under the five cards. A partition that stops summing has to be visible to the reader, not
// only to whoever reads the query — the assessment total is on the previous screen, and if these
// five do not add up to it, one of the two screens is lying about the same estate.
//
// WHAT IS NOT HERE: any percentage, any score, any estimate of how long the work takes. The
// remediation screen inherits those prohibitions from the assessment screen unchanged; a
// "3 of 5 documents remediated" progress figure is a ratio over a denominator that changes every
// time somebody applies a batch, and there is no evidence base at all for an effort estimate.
import { documentRows } from './assessMetrics.js'

/** The five lanes, in the order the screen shows them. Order is part of the contract: the identity
 *  line prints its terms in this order, and the cards above it sit in the same order, so a reader
 *  can match term to card without a legend. */
export const WORK_LANES = ['automatic', 'drafted', 'authored', 'applied', 'unfixable']

export const LANE_LABEL = {
  automatic: 'ACP applies · deterministic',
  drafted: 'Drafted · you approve',
  authored: 'You author',
  applied: 'Applied so far',
  unfixable: 'Cannot be fixed here',
}

/**
 * The criteria named by one document's entry in an `appliedCriteria` / `unfixableCriteria` map.
 *
 * Deliberately tolerant of the shape the backend actually returns, so the caller hands the response
 * straight through rather than reshaping it first. GET
 * `/scans/{id}/files/{file}/remediation-state` answers `[{rule_id, state, updated_at, last_scan_id}]`
 * where `rule_id` is a success criterion ('1.3.1') and `state` is 'not_started' | 'complete'.
 *
 * The `state` filter is IN HERE rather than in the caller on purpose. "Applied" is the one lane
 * that can only grow by taking findings out of the other four, so a caller that forgot to drop the
 * `not_started` rows would silently report unstarted work as done — and it would look right,
 * because the total would still sum. Doing it here means there is one place to get it wrong.
 */
export function criteriaNamed(entries) {
  const out = new Set()
  for (const e of entries || []) {
    if (typeof e === 'string') { if (e) out.add(e) ; continue }
    if (!e) continue
    // A row carrying a state is only counted in its terminal one. A row with no `state` field at
    // all is a plain caller-supplied criterion and is taken at face value.
    if ('state' in e && e.state !== 'complete') continue
    const sc = e.sc || e.rule_id || e.ruleId || ''
    if (sc) out.add(String(sc))
  }
  return out
}

/**
 * Which lane one finding belongs in. Exported so a test can assert the precedence directly rather
 * than inferring it from five counts.
 *
 * Precedence, first match wins:
 *   1. applied    — a corrected copy already carries this fix; it is not outstanding work.
 *   2. unfixable  — the run reported it cannot be addressed here.
 *   3. fixMode    — auto | assisted | human, the capability table's answer for (format, criterion).
 *
 * `fixMode` comes from `documentRow`, which reads it from the shared capability map. An absent
 * (format, criterion) pair resolves to 'human' there, so an unknown criterion lands in `authored`
 * — the lane that asks a person to look — and never in `automatic`.
 */
export function laneOfFinding(finding, applied, unfixable) {
  const sc = finding?.sc
  if (applied && applied.has(sc)) return 'applied'
  if (unfixable && unfixable.has(sc)) return 'unfixable'
  if (finding?.fixMode === 'auto') return 'automatic'
  if (finding?.fixMode === 'assisted') return 'drafted'
  return 'authored'
}

const emptyLane = () => ({ count: 0, findings: [], files: new Set(), criteria: new Set() })

/**
 * The remediation partition over an estate.
 *
 * Returns `null` when there is nothing to reason about — no file list, or a failed read that
 * parsed to an object. The caller renders NOTHING on null, and in particular must not render five
 * zeros: "0 automatic fixes" is a run that found no deterministic work, and a run that has not
 * happened is not that. Same reason, same rule, as `assessMetrics`.
 *
 * @param files              the scan's file rows — the SAME array the assessment screen was given
 * @param cap                remediation-capability map {fmt:{sc:'auto'|'assisted'|'human'}}
 * @param assessment         assessment-lane map, for the finding filter documentRow applies
 * @param criteria           the agreed criteria (defaults to the agreed scope inside documentRow)
 * @param level              conformance target
 * @param appliedCriteria    {[file]: rows} — per-document remediation state. See `criteriaNamed`.
 *                           This is the ONLY input that can move a finding out of the outstanding
 *                           lanes, and it is per (document, criterion) because that is the grain
 *                           the backend records at: it re-scans the corrected bytes and marks a
 *                           criterion complete only where the criterion no longer appears.
 * @param unfixableCriteria  {[file]: rows} — criteria this run reported it cannot address here.
 *                           Empty by default: nothing in the file list implies it, and inventing
 *                           it would put findings in a lane nobody can act on.
 */
export function remediationWork(files, { cap, assessment, criteria, level = 'AA',
                                         appliedCriteria = {}, unfixableCriteria = {} } = {}) {
  const all = documentRows(files, { cap, assessment, criteria, level })
  if (!all) return null

  const rows = all.filter((r) => r.opened)
  const lanes = {}
  for (const k of WORK_LANES) lanes[k] = emptyLane()

  let assessmentTotal = 0
  const documentsWithFindings = new Set()

  for (const row of rows) {
    assessmentTotal += row.totalFindings
    if (row.totalFindings) documentsWithFindings.add(row.file)
    const applied = criteriaNamed(appliedCriteria[row.file])
    const unfixable = criteriaNamed(unfixableCriteria[row.file])
    for (const f of row.findings) {
      const lane = lanes[laneOfFinding(f, applied, unfixable)]
      lane.count++
      lane.findings.push({ ...f, file: row.file, name: row.name })
      lane.files.add(row.file)
      lane.criteria.add(f.sc)
    }
  }

  // Sets are an implementation detail of the loop above; the screen wants stable, sorted lists it
  // can render and hand back to an action without re-deriving an order.
  for (const k of WORK_LANES) {
    lanes[k] = {
      count: lanes[k].count,
      findings: lanes[k].findings,
      files: [...lanes[k].files].sort(),
      criteria: [...lanes[k].criteria].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })),
    }
  }

  return {
    lanes,
    // The population every lane is a subset of, and the number the assessment screen printed.
    assessmentTotal,
    documentsAssessed: rows.length,
    documentsWithFindings: documentsWithFindings.size,
    // Handed out rather than recomputed by the caller, so the partition and anything rendered
    // beneath it can never come from two different passes over the estate.
    rows,
  }
}

/**
 * The identity the panel prints, and whether it holds.
 *
 * Rendered, never merely asserted in a test. `ok` false means the screen has a bug and the reader
 * can see it in the same glance as the numbers — which is the entire reason the line is on screen
 * rather than in a unit test.
 */
export function reconcileWork(w) {
  if (!w) return null
  const terms = WORK_LANES.map((k) => w.lanes[k].count)
  const sum = terms.reduce((a, b) => a + b, 0)
  return {
    ok: sum === w.assessmentTotal,
    line: `${terms.join(' + ')} = ${w.assessmentTotal} finding${w.assessmentTotal === 1 ? '' : 's'}`,
    sum,
  }
}

/**
 * What a batch of the deterministic fixes would actually cover — the sentence beside the button.
 *
 * Names the criteria and counts the documents. It does NOT name the fixes in prose ("table headers,
 * heading tags, document language") because that list would be a hand-maintained second copy of the
 * capability table, and the moment the table gains a criterion the prose is wrong while still
 * reading as authoritative.
 *
 * Returns null when there is no deterministic work, so the caller renders no button rather than a
 * disabled one over "0 fixes".
 */
export function batchScope(w) {
  if (!w) return null
  const lane = w.lanes.automatic
  if (!lane.count) return null
  return {
    count: lane.count,
    files: lane.files,
    documents: lane.files.length,
    criteria: lane.criteria,
  }
}
