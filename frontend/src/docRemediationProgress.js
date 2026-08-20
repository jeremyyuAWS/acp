// R7 — where ONE document is in the remediation pipeline right now, and what is left.
//
// Two modules already exist near this question and neither answers it, which is why this is a third
// rather than an edit to either:
//   • processingDetails.js — the live SCAN fan-out. Its rows are "did this file finish assessment,
//     and what did it score". That is the stage before remediation begins.
//   • remediationTrack.js  — a classifier for a CRITERION ("does ACP auto-apply this?"). It says
//     nothing about a particular document's progress, and cannot: it never sees a finding.
//
// The stage precedence itself is NOT re-derived here. It is `workflowStatusOf` from
// remediationInboxModel.js — already the shipped definition, already tested — with exactly one
// split made explicit, because the pipeline question needs a distinction the tab question does not:
// its `completed` bucket holds both "the re-scan confirmed the fix" and "settled with no fix
// written". Reporting those as one number is how a document reads as remediated when nothing was
// written to it. Everything else is a rename, so the two surfaces cannot drift apart.
//
// ADR 0020: Discover LISTS files — `classify_from_metadata`, no bytes, no analysis. So there is no
// discovery stage in this pipeline and nothing here may suggest content was read before Assess.
// The first thing that opened this document was the assessment; that is where the count starts.
//
// ADR 0016 / "missing data is not measured zero": a queue that has not loaded returns **null**, not
// a set of zeros. A caller cannot accidentally render "0 findings, all done" for a pending fetch.

import { workflowStatusOf, docProgress, laneOf } from './remediationInboxModel.js'

// The pipeline, in the order a finding moves through it. `spine` marks the linear path; the two
// off-spine stages are outcomes that leave it. `needs` says WHO the stage is waiting on — the one
// fact "what is left" is actually built from.
export const STAGES = [
  { key: 'to-review', label: 'Needs your review', spine: true, needs: 'person',
    hint: 'A proposed or applied fix is waiting for a decision.' },
  { key: 'authoring', label: 'Needs hand authoring', spine: true, needs: 'person',
    hint: 'Nothing ACP can safely write — a person edits the document.' },
  { key: 'written', label: 'Fix written, not confirmed', spine: true, needs: 'system',
    hint: 'The change is in the corrected copy. The re-scan has not confirmed it yet.' },
  { key: 'confirmed', label: 'Confirmed by re-scan', spine: true, needs: null,
    hint: 'The re-scan read the corrected copy and the finding had gone.' },
  { key: 'settled', label: 'Settled without a fix', spine: false, needs: null,
    hint: 'Rejected, or judged not applicable. No fix was written and none is pending.' },
  { key: 'blocked', label: 'Blocked', spine: false, needs: null,
    hint: 'Cannot be remediated as it stands.' },
]

export const STAGE_KEYS = STAGES.map((s) => s.key)
const STAGE_BY_KEY = new Map(STAGES.map((s) => [s.key, s]))
export const stageOfKey = (key) => STAGE_BY_KEY.get(key) || null

// workflowStatusOf's five buckets → this pipeline's names. 'completed' is absent deliberately: it
// is the one that splits, below.
const FROM_WORKFLOW = {
  'needs-review': 'to-review',
  manual: 'authoring',
  'awaiting-validation': 'written',
  blocked: 'blocked',
}

/** The pipeline stage one finding sits in. Same precedence as the workflow tabs — one definition —
 *  except that `completed` is split into the two facts it conflates. */
export function findingStage(f, decisions = {}) {
  const w = workflowStatusOf(f, decisions)
  if (w !== 'completed') return FROM_WORKFLOW[w] || 'to-review'
  // Confirmed means the backend re-scanned the corrected copy and the criterion had gone — the
  // `verified` status and nothing else. A rejection or a not-applicable judgement is settled, but
  // no fix exists for it, and it must never be counted as one that cleared.
  return String(f?.status || '').toLowerCase() === 'verified' ? 'confirmed' : 'settled'
}

/** Where a document is in the remediation pipeline, and what remains.
 *
 *  `queue` is the document's findings (the remediation queue). **null/undefined → null**: not
 *  loaded is not "nothing to do". `file` selects one document's findings; pass null to report the
 *  whole queue. `decisions` is the inbox's decision map, keyed by finding id (or file).
 *
 *  Returns counts per stage, the identity line those counts must satisfy, the stage the document is
 *  currently held at, and the remaining reviewer effort — the last borrowed whole from
 *  `docProgress`, so the estimate here is the same estimate the workspace bar shows. */
export function docRemediationProgress(queue, file = null, decisions = {}) {
  if (queue == null) return null
  const items = file == null ? queue : queue.filter((f) => (f?.file || '') === file)
  const counts = Object.fromEntries(STAGE_KEYS.map((k) => [k, 0]))
  for (const f of items) counts[findingStage(f, decisions)] += 1

  const total = items.length
  const stages = STAGES.map((s) => ({ ...s, count: counts[s.key] }))
  const sum = STAGE_KEYS.reduce((n, k) => n + counts[k], 0)

  // The partition printed on screen, #551's discipline: a broken split is visible to the reader,
  // not only to whoever reads the code. Every finding is in exactly one stage, so this must hold.
  const reconcile = {
    parts: STAGE_KEYS.map((k) => counts[k]),
    sum,
    total,
    ok: sum === total,
    line: `${STAGE_KEYS.map((k) => counts[k]).join(' + ')} = ${total} finding${total === 1 ? '' : 's'}`,
  }

  const needsPerson = counts['to-review'] + counts.authoring
  const needsSystem = counts.written
  const done = counts.confirmed + counts.settled

  // Where the document is held: the earliest spine stage that still holds work. null when nothing is
  // outstanding — which is the "this document is through the pipeline" signal.
  const at = stages.find((s) => s.spine && s.needs && s.count > 0) || null

  // Effort: reuse the shipped estimate rather than inventing a second one. It is a per-lane ESTIMATE
  // (remediationInboxModel.effortSecOf), not a measurement, and the UI labels it as one.
  const effort = docProgress(items, null, decisions)

  return {
    file, total, counts, stages, reconcile,
    needsPerson, needsSystem, done,
    blocked: counts.blocked,
    confirmed: counts.confirmed,
    // Fraction of the document's findings that have reached a terminal, non-blocked outcome.
    // null — not 0 — when there is nothing to take a fraction of.
    pct: total > 0 ? Math.round((done / total) * 100) : null,
    at,
    // Blocked counts against completeness. Without that clause a document whose every finding is
    // unremediable reports `complete: true` — nothing is outstanding because nothing can be done —
    // which is the single most misleading thing this module could say. `allBlocked` is the separate,
    // honest name for that state.
    complete: total > 0 && needsPerson === 0 && needsSystem === 0 && counts.blocked === 0,
    remainingSec: effort.remainingSec,
    remainingLabel: effort.remainingLabel,
  }
}

/** The one-line answer to "what is left", built only from stages that are waiting on somebody.
 *  Empty string when nothing is outstanding — the caller renders the done state instead. */
export function remainingSummary(p) {
  if (!p) return ''
  const bits = []
  if (p.needsPerson > 0) bits.push(`${p.needsPerson} need${p.needsPerson === 1 ? 's' : ''} you`)
  if (p.needsSystem > 0) bits.push(`${p.needsSystem} awaiting the re-scan`)
  if (p.blocked > 0) bits.push(`${p.blocked} blocked`)
  return bits.join(' · ')
}

/** True when every finding this document has is blocked — a document with no route through the
 *  pipeline at all, which reads very differently from one that is finished. */
export function allBlocked(p) {
  return !!p && p.total > 0 && p.blocked === p.total
}

// Re-exported so a caller can label a single finding with the same vocabulary the panel uses without
// reaching into the inbox model for laneOf as well.
export { laneOf }
