// R12 · Close the loop — what happens after delivery: re-verification, the compliance record, and
// the handoff back to Assess.
//
// GROUND TRUTH — the remediation job's own tail, api/handlers.py:758-827:
//
//   :760   `residual = _verify_residual_scs(fixed_bytes, filename)` — the fixed BYTES are
//          re-scanned. Not the source, not the original findings: the copy that was produced.
//   api/proposals.py:162-184  that function returns the set of SCs STILL failing, or **None when
//          the re-scan could not run**. The backend then takes a deliberate "credit it" posture on
//          None (never penalise remediation for an infra hiccup) — but a UI that copies that
//          posture would tell an operator a criterion was VERIFIED when nothing verified it. So
//          `None` maps to UNVERIFIED here, which is neither a pass nor a fail.
//   :793-799  a rule whose id is in `residual` is KEPT failing; everything else is
//          `upsert_remediation_state(..., "complete")` and joins `cleared`.
//   :800-802  `remediate.unverified` is logged when the re-scan ran and something stayed failing.
//   :781-786  before→after diffs are recorded ONLY for criteria not still failing — a fix that did
//          not clear never reaches the report.
//   :812-820  every FAIL this run did not verifiably clear is routed to a human
//          (`queue_hitl_review_for_file` → `hitl.review_routed`).
//   :821-824  a fully-cleared file still gets ONE verification item ("auto/verify"), so no
//          unreviewed fix reaches Publish on trust alone.
//
// And the boundary the handoff must respect — ADR 0020: Discover LISTS, and never opens a file.
// Re-checking a document is an Assess action. Nothing here may imply a re-check happens in
// Discover, or that Discover reads bytes.
//
// Prior art this deliberately matches rather than duplicates: graduation.js models the SET-level
// promotion from a conditional release to full certification, and releasePolicy.js owns the
// release wording. This module covers the step BEFORE those — one remediation run's outcome, and
// where it sends the operator next.

// What the re-scan established about one document. Four states, because "we could not check" is
// not one of the other three.
export const VERIFY = {
  CLEARED: 'cleared',                // re-scan ran; nothing this run fixed is still failing
  STILL_FAILING: 'still-failing',    // re-scan ran; a reported fix did not take
  UNVERIFIED: 'unverified',          // the re-scan could not run — no evidence either way
  NOT_REMEDIATED: 'not-remediated',  // nothing was applied to this document
}

const ids = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string' && x) : [])

/**
 * Whether the re-scan ran for this document.
 *
 * Accepts the shape the job produces: `rescan: 'ran' | 'unavailable'`, or a boolean, or nothing at
 * all. Anything that is not an explicit "it ran" is treated as not having run — the direction that
 * under-claims rather than over-claims.
 */
function rescanRan(doc) {
  const r = doc?.rescan
  if (r === true || r === 'ran') return true
  return false
}

/**
 * One document's position in the loop.
 *
 * `cleared` is only ever populated when the re-scan actually ran. A document whose re-scan did not
 * run reports its fixes as `applied` but claims nothing as verified, because nothing verified them
 * — the backend credits them to avoid penalising a fix for an infra failure, and that is a storage
 * decision, not a statement to put in front of an auditor.
 */
export function docCloseout(doc) {
  const file = doc?.file ?? null
  const applied = ids(doc?.applied ?? doc?.cleared)
  const cleared = ids(doc?.cleared)
  const kept = ids(doc?.kept)
  const remediated = !!(doc?.remediated_at || doc?.blob_url || doc?.drive_write_url
    || applied.length || cleared.length || kept.length)
  // `pendingReview` is a count when it is known and null when it is not — an absent queue read is
  // not an empty queue.
  const pendingReview = typeof doc?.pendingReview === 'number' ? doc.pendingReview : null

  let state
  if (!remediated) state = VERIFY.NOT_REMEDIATED
  else if (!rescanRan(doc)) state = VERIFY.UNVERIFIED
  else if (kept.length) state = VERIFY.STILL_FAILING
  else state = VERIFY.CLEARED

  return {
    file,
    state,
    // Verified-cleared criteria — empty unless the re-scan ran, whatever the record claims.
    cleared: state === VERIFY.CLEARED || state === VERIFY.STILL_FAILING ? cleared : [],
    kept: rescanRan(doc) ? kept : [],
    applied,
    pendingReview,
    published: !!doc?.published_at,
  }
}

/**
 * A human sentence for one document's state. Each is a statement about EVIDENCE, not about effort:
 * "we re-scanned and it cleared" / "we re-scanned and it did not" / "we could not re-scan".
 */
export function verifyLine(closeout) {
  const c = closeout || {}
  const n = c.cleared?.length || 0
  const k = c.kept?.length || 0
  switch (c.state) {
    case VERIFY.CLEARED:
      return `Re-scanned after the fix: ${n} ${n === 1 ? 'criterion' : 'criteria'} no longer ${n === 1 ? 'fails' : 'fail'}.`
    case VERIFY.STILL_FAILING:
      return `Re-scanned after the fix: ${n} ${n === 1 ? 'criterion' : 'criteria'} cleared, ${k} still ${k === 1 ? 'fails' : 'fail'} and ${k === 1 ? 'has' : 'have'} been sent to review.`
    case VERIFY.UNVERIFIED:
      return 'The re-scan could not run on this copy, so nothing here is verified — the fixes were applied, and no evidence has been recorded that they took.'
    default:
      return 'Nothing has been applied to this document yet.'
  }
}

/**
 * Roll one run up. Every count is a measurement of something read; `pendingReview` is null when no
 * document reported a queue count, so an unread queue never renders as "0 awaiting review".
 */
export function closeoutSummary(docs = []) {
  const list = (docs || []).filter(Boolean).map(docCloseout)
  const by = (s) => list.filter((d) => d.state === s)
  const known = list.filter((d) => d.pendingReview !== null)
  return {
    total: list.length,
    cleared: by(VERIFY.CLEARED).length,
    stillFailing: by(VERIFY.STILL_FAILING).length,
    unverified: by(VERIFY.UNVERIFIED).length,
    notRemediated: by(VERIFY.NOT_REMEDIATED).length,
    published: list.filter((d) => d.published).length,
    // null = nobody told us. 0 = somebody told us, and it was zero.
    pendingReview: known.length ? known.reduce((a, d) => a + d.pendingReview, 0) : null,
    docs: list,
  }
}

// What the run wrote down, in the order it wrote it. Each entry names the thing in the audit trail
// so a reader can go and find it, and each is gated on having actually happened rather than being
// a fixed list of reassurances.
export function complianceRecord(summary) {
  const s = summary || {}
  const rows = []
  if (s.total) {
    rows.push({
      key: 'applied',
      label: 'Fixes applied',
      detail: `Recorded per document as remediate.applied in the decision log, with the list of what changed.`,
    })
  }
  if (s.cleared || s.stillFailing) {
    rows.push({
      key: 'verified',
      label: 'Re-scan evidence',
      detail: 'The corrected copy was re-scanned and each criterion credited only if it actually stopped failing. Before→after evidence is kept for those criteria and dropped for any fix that did not take, so the report cannot show a fix that never landed.',
    })
  }
  if (s.stillFailing) {
    rows.push({
      key: 'unverified-log',
      label: 'Fixes that did not take',
      detail: `${s.stillFailing} ${s.stillFailing === 1 ? 'document' : 'documents'} reported a fix that the re-scan found still failing. Logged as remediate.unverified and left failing rather than credited.`,
    })
  }
  if (s.unverified) {
    rows.push({
      key: 'no-evidence',
      label: 'No re-scan evidence',
      detail: `${s.unverified} ${s.unverified === 1 ? 'document' : 'documents'} could not be re-scanned, so ${s.unverified === 1 ? 'its fixes carry' : 'their fixes carry'} no verification either way. Re-run the check before releasing ${s.unverified === 1 ? 'it' : 'them'}.`,
    })
  }
  if (s.pendingReview) {
    rows.push({
      key: 'review',
      label: 'Routed to human review',
      detail: `${s.pendingReview} finding${s.pendingReview === 1 ? '' : 's'} reached the review queue (hitl.review_routed). Every finding a fix did not verifiably clear goes to a person; a fully-cleared document still gets one verification item, so no unreviewed fix reaches Publish on trust alone.`,
    })
  }
  if (s.published) {
    rows.push({
      key: 'released',
      label: 'Released',
      detail: `${s.published} ${s.published === 1 ? 'document is' : 'documents are'} recorded as released, with the timestamp, in the audit trail.`,
    })
  }
  return rows
}

// Where the operator goes next. One step, chosen by what is most blocking — a screen that offers
// four equal buttons is a screen that has not decided.
export const NEXT = {
  REVERIFY: 'reverify',
  REMEDIATE: 'remediate',
  REVIEW: 'review',
  PUBLISH: 'publish',
  NOTHING: 'nothing',
}

/**
 * The handoff.
 *
 * Ordered by what blocks certification hardest: a document with NO evidence is the worst state to
 * carry forward silently, so it outranks a document that is honestly still failing.
 *
 * `assessNote` exists because "re-check this document" must not read as a Discover action. ADR
 * 0020: Discover lists an estate and never opens a file; opening the bytes is Assess.
 */
export function nextStep(summary) {
  const s = summary || {}
  if (s.unverified) {
    return {
      key: NEXT.REVERIFY,
      label: `Re-check ${s.unverified} document${s.unverified === 1 ? '' : 's'}`,
      detail: `${s.unverified} corrected ${s.unverified === 1 ? 'copy has' : 'copies have'} no re-scan behind ${s.unverified === 1 ? 'it' : 'them'}. Re-checking reads the corrected copy again and records what actually cleared.`,
    }
  }
  if (s.stillFailing) {
    return {
      key: NEXT.REMEDIATE,
      label: `Return ${s.stillFailing} document${s.stillFailing === 1 ? '' : 's'} to remediation`,
      detail: `A reported fix did not clear on the re-scan. ${s.stillFailing === 1 ? 'That document is' : 'Those documents are'} still failing and ${s.stillFailing === 1 ? 'has' : 'have'} been routed to review — nothing was credited on trust.`,
    }
  }
  if (s.pendingReview) {
    return {
      key: NEXT.REVIEW,
      label: `Review ${s.pendingReview} finding${s.pendingReview === 1 ? '' : 's'}`,
      detail: 'A document becomes releasable once every review item on it is approved. Even a fully-cleared document carries one verification item, so a fix is never released unread.',
    }
  }
  if (s.cleared) {
    return {
      key: NEXT.PUBLISH,
      label: `Release ${s.cleared} verified document${s.cleared === 1 ? '' : 's'}`,
      detail: 'Each was re-scanned after its fix and its review items approved. Releasing records the outcome in the audit trail; it verifies the criteria in scope and does not certify overall conformance.',
    }
  }
  return { key: NEXT.NOTHING, label: 'Nothing to hand off yet', detail: 'No document in this run has been remediated.' }
}

// The one sentence about where a re-check happens, so the phase boundary is stated on the screen
// that invites one rather than left to be inferred.
export const ASSESS_HANDOFF_NOTE =
  'Re-checking a document is an Assess step: it reads the corrected copy and re-runs the criteria in scope. Discover only lists what exists in the estate and never opens a file.'
