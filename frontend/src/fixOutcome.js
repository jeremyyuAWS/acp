// R8 — what happened when ACP tried to fix a document, and the four ways that is not one question.
//
// THE DEFECT THIS MODULE EXISTS TO PREVENT. A remediation screen that shows "not fixed" over a
// document is telling a reader nothing they can act on, because at least four unrelated situations
// produce it and each has a different next step:
//
//   · the job FAILED           — a worker threw, a token expired, the source went away. The document
//                                is fine and the run is what broke. Somebody retries it.
//   · the run REFUSED          — the run reached this document, looked at it, and declined. Nothing
//                                in it is in the deterministic lane, or the format has no fixer, or
//                                the operator's scope excluded it. Nothing broke. Retrying changes
//                                nothing; the work moves to a person.
//   · nothing was ATTEMPTED    — no remediation job for this document exists, and no run recorded a
//                                decision about it. The record is silent, and silence is not an
//                                outcome.
//   · the scan never READ it   — the document was never assessed, so there were no findings to
//                                remediate. This is upstream of remediation entirely.
//
// Collapsing any of those into "failed" sends someone to inspect a document that is not the problem
// — the exact failure `fileErrorReason.js` was written for, when "file unreadable" was shown over 22
// SharePoint documents that had never been fetched.
//
// EVERY STATE HERE IS READ OFF A PERSISTED ROW. Two sources, both already served to the client:
//
//   · the durable job queue (`getJobs`) — status / attempts / max_attempts / last_error. This module
//     defers to `FailureLane.classifyFailure` for the dead-vs-retrying call rather than re-deriving
//     it, so the two surfaces cannot start disagreeing about what a dead-letter is.
//   · the immutable decision log (`listScanDecisions` → GET /decisions) — `api/handlers.py` records
//     every one of these outcomes per file as it happens:
//         remediate.applied           what the fix pass did
//         remediate.unverified        reported fixed, still failing on the post-fix re-scan
//         remediate.deferred          no server-side remediator for .ext / no deterministic fixes applied
//         remediate.out_of_scope      the criterion is outside the operator's scope
//         remediate.skipped           ACP's own remediated copy, not a source document
//         remediate.drive_mirror_failed   the Drive copy failed — see below, this is NOT a failed fix
//         apply.unsupported           no approved-value applier for this format
//         apply.no_remediated_copy    nothing to write the approved value into
//         scan.file_error / scan.file_timeout   the scan never produced a result for this file
//
// A FAILED DRIVE MIRROR IS NOT A FAILED FIX, and this is the claim most likely to be got wrong.
// ADR 0010 made Azure Blob the primary, must-succeed store and demoted the Drive write to a
// best-effort mirror: `remediate_file` uploads to Blob first, and only then — when
// `store.get_drive_mirror_enabled()` is true, which is the DEFAULT ("true" unless explicitly set to
// "false") — also writes a copy into a "Remediated" folder in the source drive. When that upload
// throws, the handler logs `remediate.drive_mirror_failed` and carries on; the corrected copy exists
// and the remediation succeeded. So this module carries the mirror failure as a NOTE against an
// otherwise-successful outcome, never as the outcome itself.
import { classifyFailure } from './FailureLane.jsx'
import { modeFor, fmtOf } from './capability.js'

/** The states, in the precedence `outcomeFor` applies them. Exported so a caller can order by it. */
export const OUTCOMES = ['failed', 'unreadable', 'unverified', 'refused', 'applied', 'not_attempted']

export const OUTCOME_LABEL = {
  failed: 'The fix failed',
  unreadable: 'Never assessed',
  unverified: 'Applied, but did not clear',
  refused: 'Not attempted by design',
  applied: 'Fixed',
  not_attempted: 'No record of an attempt',
}

// One sentence per state saying what it MEANS, distinct from what to do about it. These are the
// sentences the three-way distinction lives in, so they say what happened rather than how bad it is.
export const OUTCOME_MEANING = {
  failed: 'A remediation job for this document ran and errored. The document itself may be fine — the run is what broke.',
  unreadable: 'The scan never produced a result for this document, so there were no findings to remediate. This is upstream of remediation.',
  unverified: 'A fix was written and the re-scan of the corrected copy still reports the criterion failing, so ACP did not credit it.',
  refused: 'A run reached this document and declined to change it. Nothing broke, and running it again produces the same answer.',
  applied: 'A run wrote a corrected copy and the re-scan confirmed the criteria it credited.',
  not_attempted: 'No remediation job and no recorded decision for this document. The record is silent — which is not the same as a failure.',
}

// The decision-log actions that mean "the run declined", each with the reading a person needs. The
// detail string on the row carries the specifics and is always shown alongside; these say what KIND
// of refusal it was, which the detail alone does not.
const REFUSAL = {
  'remediate.deferred': 'No deterministic fix ran on this document — either the format has no server-side remediator, or nothing in it was in the automatic lane.',
  'remediate.out_of_scope': 'A criterion was excluded by the operator scope, so its proposals were never enqueued.',
  'remediate.skipped': 'This is ACP’s own remediated output shadowing its source, not a source document.',
  'apply.unsupported': 'This format has no applier for approved values, so an approved fix could not be written in.',
  'apply.no_remediated_copy': 'There was no stored remediated copy to write the approved value into.',
}
const SCAN_FAILURE = new Set(['scan.file_error', 'scan.file_timeout'])
const MIRROR_FAILED = 'remediate.drive_mirror_failed'

/** The remediation jobs the queue holds for one (scan, file), newest-relevant first. */
const jobsForFile = (jobs, scanId, file) => (jobs || []).filter((jb) => {
  if (!jb || jb.type !== 'remediate_file') return false
  if (scanId && jb.scan_id !== scanId) return false
  let payload = jb.payload
  if (typeof payload === 'string') { try { payload = JSON.parse(payload || '{}') } catch { payload = {} } }
  return (payload && payload.file) === file
})

const rowsForFile = (decisions, file) => (decisions || [])
    .filter((d) => d && d.file === file)
    .sort((a, b) => String(b.ts || '').localeCompare(String(a.ts || '')))   // ISO → lexical is chronological

/**
 * What a remediation run has to work with on this document, read from the capability table.
 *
 * This is the answer to "was there anything for a run to DO here?", and it is what makes a refusal
 * legible: a document whose every finding is in the `assisted` or `human` lane has nothing in the
 * automatic lane, so a run declining to change it is the system working. Derived per (format,
 * criterion) from `modeFor`, never from a list.
 *
 * Returns null when the document's findings are not known — a caller that has not loaded the scan
 * must not be handed a zero.
 */
export function autoLaneSize(fileRow, cap) {
  if (!fileRow || !Array.isArray(fileRow.issues) || !cap) return null
  const fmt = fmtOf(fileRow)
  let auto = 0
  for (const x of fileRow.issues) {
    const sc = String(x?.wcag || '').replace(/^SC_/, '').replace(/_/g, '.').match(/\d+\.\d+\.\d+/)?.[0]
    if (sc && modeFor(cap, fmt, sc) === 'auto') auto++
  }
  return auto
}

/**
 * The outcome for one document, and everything the record says about it.
 *
 * @param file        the document
 * @param scanId      the scan; job rows are matched on it so another scan's failure is not this one's
 * @param decisions   GET /decisions rows for the scan  [{ts, actor, action, file, rule_id, detail}]
 * @param jobs        GET /jobs rows (the owner-scoped feed FailureLane reads)
 * @param loaded      false while either feed is still in flight. An unloaded outcome is `null`, not
 *                    `not_attempted` — "we have not looked" and "nothing happened" are different
 *                    answers and only one of them is about the document.
 *
 * @returns {null | {file, outcome, label, meaning, reason, reasonSource, retryable, job,
 *                   mirrorFailed, mirrorDetail, notes}}
 */
export function outcomeFor(file, { scanId = null, decisions, jobs, loaded = true } = {}) {
  if (!file) return null
  if (!loaded) return null

  const myJobs = jobsForFile(jobs, scanId, file)
  const rows = rowsForFile(decisions, file)

  // Every recorded remark about this document, kept whole. The headline state is one of these; the
  // rest are shown under it, because a run that refused ONE criterion and applied another has said
  // two true things and a screen that prints only the winner has dropped one.
  const notes = rows
      .filter((d) => REFUSAL[d.action] || SCAN_FAILURE.has(d.action) || d.action === MIRROR_FAILED
                   || String(d.action || '').startsWith('remediate.'))
      .map((d) => ({ action: d.action, detail: d.detail || '', ts: d.ts || null }))

  const mirror = rows.find((d) => d.action === MIRROR_FAILED) || null

  const base = {
    file,
    reason: '',
    reasonSource: null,
    retryable: false,
    job: null,
    // ADR 0010: the Drive copy is a best-effort mirror over a must-succeed Blob write, so its
    // failure is an annotation on the outcome and never the outcome.
    mirrorFailed: !!mirror,
    mirrorDetail: mirror ? (mirror.detail || '') : '',
    notes,
  }
  const as = (outcome, extra = {}) => ({
    ...base, outcome, label: OUTCOME_LABEL[outcome], meaning: OUTCOME_MEANING[outcome], ...extra,
  })

  // 1. A remediation job that errored. `classifyFailure` is FailureLane's own categorisation —
  //    'dead' (retries exhausted) or 'retrying' (still within the retry budget). Both are failures
  //    of the run; only the terminal one is a person's to retry, which is the same rule the
  //    operational lane applies.
  const failing = myJobs.map((jb) => ({ jb, kind: classifyFailure(jb) })).filter((x) => x.kind)
  const dead = failing.find((x) => x.kind === 'dead')
  const retrying = failing.find((x) => x.kind === 'retrying')
  if (dead || retrying) {
    const { jb, kind } = dead || retrying
    return as('failed', {
      reason: jb.last_error || '',
      reasonSource: 'job',
      retryable: kind === 'dead',
      job: { id: jb.id, status: jb.status, attempts: jb.attempts || 0,
             maxAttempts: jb.max_attempts || 0, kind },
    })
  }

  // 2. The scan never produced a result, so there was nothing to remediate. Upstream of everything
  //    below, and the one state where the next step is to re-run the SCAN rather than the fix.
  const scanFail = rows.find((d) => SCAN_FAILURE.has(d.action))
  if (scanFail) {
    return as('unreadable', { reason: scanFail.detail || '', reasonSource: 'decision', retryable: false })
  }

  // 3. A fix was written and did not clear on the re-scan. Deliberately ABOVE `applied`: the same
  //    run logs both when it credits some criteria and keeps others, and the kept ones are the part
  //    a reader has to know about.
  const unverified = rows.find((d) => d.action === 'remediate.unverified')
  if (unverified) {
    return as('unverified', { reason: unverified.detail || '', reasonSource: 'decision' })
  }

  // 4. The run declined.
  const refused = rows.find((d) => REFUSAL[d.action])
  if (refused) {
    return as('refused', { reason: REFUSAL[refused.action], reasonSource: 'decision',
                           detail: refused.detail || '' })
  }

  // 5. It worked.
  const applied = rows.find((d) => d.action === 'remediate.applied')
  if (applied) {
    return as('applied', { reason: applied.detail || '', reasonSource: 'decision' })
  }

  // 6. Nothing. A job that is queued or running is not an outcome either — it is a run in flight,
  //    reported as such rather than as an absence.
  const inFlight = myJobs.find((jb) => jb.status === 'queued' || jb.status === 'running')
  return as('not_attempted', {
    reason: inFlight ? 'A remediation job for this document is in the queue and has not finished.' : '',
    reasonSource: inFlight ? 'job' : null,
    job: inFlight ? { id: inFlight.id, status: inFlight.status, attempts: inFlight.attempts || 0,
                      maxAttempts: inFlight.max_attempts || 0, kind: 'in_flight' } : null,
  })
}

/**
 * The outcomes for a list of documents, grouped by state.
 *
 * Returns null when the feeds have not loaded. The grouping keeps every state present as a key with
 * an empty array — a caller rendering "0 failed" over a loaded scan is saying something true, where
 * one rendering it over an unloaded scan would not be, and null is how that second case is refused.
 */
export function outcomeSummary(files, opts = {}) {
  if (!Array.isArray(files) || opts.loaded === false) return null
  const by = Object.fromEntries(OUTCOMES.map((o) => [o, []]))
  for (const f of files) {
    const name = typeof f === 'string' ? f : (f && (f.file || f.name))
    const r = outcomeFor(name, opts)
    if (r) by[r.outcome].push(r)
  }
  return by
}
