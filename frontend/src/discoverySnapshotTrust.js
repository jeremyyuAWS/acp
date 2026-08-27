// Is this run's inventory the whole estate, or only part of it?
//
// handlers._scan_discover records `scope.enumeration` at listing time — {complete, auth_ok,
// files_found, truncated, folders_visited} — precisely so the answer does not have to be
// re-derived from scattered scope fields. Nothing read it until this module: a truncated listing
// rendered its partial counts on the Discover tab exactly like a complete one, which is the
// silent-zero failure in its less dramatic form (a wrong number rather than no number).
//
// WHY NOT published_at. scan_runs.published_at looks like the natural signal — the backend stamps
// it only when enumeration was complete — but its ABSENCE does not mean the snapshot is bad. The
// stamp is skipped on `_checkpoint_resume`, so a scan that crashed once, resumed, and finished
// perfectly well is unpublished too. Treating unpublished as untrustworthy would warn on healthy
// retried scans, and a banner that cries wolf on a good scan is worse than no banner. So this
// reads only positive evidence recorded at listing time.

/** Verdict for a discovery run, or null when there is nothing to claim.
 *
 *  Null — not a pass — is the answer for a run with no `scope.enumeration`: every scan predating
 *  the flag has none, and reporting those as incomplete would put a warning on all history.
 *  Silence about an unknown beats a guess.
 *
 *  Returns { partial: true, reason, filesFound } or { partial: false }.
 */
export function snapshotTrust(run) {
  const enumeration = run?.scope?.enumeration
  if (!enumeration || typeof enumeration !== 'object') return null

  // A failed run already has its own banner on the Discover tab, and it says something stronger
  // ("discovery did not finish"). Two alerts about one run read as two problems.
  if (run?.status === 'failed') return null

  const filesFound = Number.isFinite(enumeration.files_found) ? enumeration.files_found : null

  // truncated is the concrete cause — the listing stopped at FANOUT_MAX_FILES — so it is worth
  // distinguishing from a generic incomplete, which is what `complete: false` alone would say.
  if (enumeration.truncated === true) return { partial: true, reason: 'truncated', filesFound }
  if (enumeration.complete === false) return { partial: true, reason: 'incomplete', filesFound }
  return { partial: false }
}

/** What to tell the reader. Names the mechanism and what to do — "may be incomplete" is true of
 *  every listing and warns nobody. */
export function snapshotTrustMessage(verdict) {
  if (!verdict?.partial) return null
  const counted = verdict.filesFound != null
    ? `${verdict.filesFound.toLocaleString()} files were listed before it stopped. `
    : ''
  if (verdict.reason === 'truncated') {
    return {
      title: 'This inventory is part of the estate, not all of it',
      body: `${counted}The listing hit its per-run file cap, so the counts below describe what was `
          + 'reached — not the whole source. Narrow the scan to specific folders and run it again '
          + 'to inventory the rest.',
    }
  }
  return {
    title: 'This inventory may be incomplete',
    body: `${counted}Discovery could not confirm it listed the whole source, so treat the counts `
        + 'below as a floor rather than the estate. Re-run discovery to get a verified inventory.',
  }
}
