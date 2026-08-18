// W5 — graduating a CONDITIONAL release to full certification without a whole-estate re-scan.
//
// A release can go out while some in-scope documents are still HELD: the documents ACP verified in
// scope are released, the rest wait for remediation. That is a conditional release — correct and
// honest, but today it terminates there. When the held documents are later remediated and
// individually re-validated (each already re-scans its own fixed copy on the remediate path),
// nothing promotes the set from "conditional" to "fully certified" except re-running the whole
// scan — which re-does, for the whole estate, work already done per document.
//
// This is the pure model for that promotion. It reads only what Publish already has — the scan's
// in-scope files (each with `.compliant` and a release marker) and the session's just-released
// set — and derives the set-level status plus the exact files a graduation would release. No new
// data and no re-scan: graduation releases the now-verified formerly-held documents through the
// SAME publish path an ordinary release uses.

export const SET_STATUS = {
  NONE: 'none',                 // nothing released yet — the ordinary "ready to release" screen
  CONDITIONAL: 'conditional',   // released, but documents are still held → cannot be full yet
  GRADUATABLE: 'graduatable',   // every held document is now verified → release them to reach full
  FULL: 'full',                 // every in-scope document is released
}

// A document is HELD (part of the certification set, but not yet verified) when it is an ASSESSED
// document still carrying open work. A discover-only / never-assessed record (no score, no
// findings) is NOT part of the set — counting it as held would keep a set eternally conditional
// over a file nobody chose to certify.
export function isHeldDoc(f) {
  if (!f || f.compliant) return false
  if (Array.isArray(f.issues)) return f.issues.length > 0
  if (typeof f.needs_remediation === 'number') return f.needs_remediation > 0
  return f.score != null   // assessed (has a score) but not compliant → held
}

// The documents that make up the certification set: verified (compliant) OR held (assessed with
// open work). Everything else is out of the lifecycle this screen certifies.
export function certificationUniverse(files = []) {
  return (files || []).filter((f) => f && (f.compliant || isHeldDoc(f)))
}

// Derive the set-level release status from the certification universe, the session's released map
// (`done[file] === true`), and any files that arrived already certified (external upload).
//
// `files` should be the certification universe (see certificationUniverse) — the caller passes it
// pre-filtered so the model stays a pure function of released-vs-held.
export function releaseSetStatus(files = [], done = {}, certified = []) {
  const certifiedSet = new Set((certified || []).map((c) => c.file))
  const isReleased = (f) => !!done[f.file] || !!f.published_at || certifiedSet.has(f.file)

  const total = files.length
  const released = files.filter(isReleased)
  const unreleased = files.filter((f) => !isReleased(f))
  const heldOpen = unreleased.filter((f) => !f.compliant)          // still genuinely not certifiable
  const verifiedUnreleased = unreleased.filter((f) => f.compliant) // now pass → a graduation releases these

  let status = SET_STATUS.NONE
  if (total > 0 && released.length === total) {
    status = SET_STATUS.FULL
  } else if (released.length > 0 && heldOpen.length === 0 && verifiedUnreleased.length > 0) {
    // Every document that was held is now verified — releasing them completes the set to full,
    // and each was already re-validated on its own remediation path, so no re-scan is required.
    status = SET_STATUS.GRADUATABLE
  } else if (released.length > 0 && (heldOpen.length > 0 || verifiedUnreleased.length > 0)) {
    status = SET_STATUS.CONDITIONAL
  }

  return {
    status,
    total,
    released: released.length,
    heldOpen: heldOpen.length,
    verifiedUnreleased: verifiedUnreleased.length,
    // The exact files a "graduate to full" action would release — the ones held at release time
    // that now pass. Empty unless a graduation is actually available or in progress.
    graduatable: verifiedUnreleased.map((f) => f.file),
  }
}
