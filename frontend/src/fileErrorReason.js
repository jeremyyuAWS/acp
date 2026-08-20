// Why a document came back with no findings and no score.
//
// `status='error'` is a CATCH-ALL. handlers wraps download-and-analyse in one try, and anything
// that raises lands here:
//
//     if fdict is None:                              # fetch/analyse failed → error record
//
// So the drawer's old sentence — "Could not analyse — file unreadable" — asserted two things the
// record does not support: that the file was READ (it may never have been fetched), and that the
// FILE is at fault (it may be a credential, a route, a cap). On 2026-08-19 that sentence was shown
// over 22 SharePoint documents that were never fetched at all, because the download was routed to
// the wrong API. The message sent everyone looking at the documents; the bug was in the plumbing.
//
// The real reason was recorded the whole time. handlers logs it per file:
//
//     log_decision("system", "scan.file_error", scan_id=…, file=name, detail=f"{type(e).__name__}: {e}"[:200])
//
// and `GET /decisions?scan_id=…` returns it. This module turns that log into the one line a reader
// needs, and — the part that matters — REFUSES to invent one when the log has nothing.

/** The recorded reason for one file, or null when nothing was recorded. */
export function errorReasonFor(decisions, file) {
  if (!Array.isArray(decisions) || !file) return null
  // Newest first: a file re-tried within a scan logs twice, and the LAST attempt is the one whose
  // outcome the record reflects. `ts` is an ISO string, so lexical order is chronological.
  const rows = decisions
    .filter((d) => d && d.action === 'scan.file_error' && d.file === file && d.detail)
    .sort((a, b) => String(b.ts || '').localeCompare(String(a.ts || '')))
  return rows.length ? String(rows[0].detail) : null
}

/**
 * What the drawer says over a document with no findings.
 *
 * Three states, deliberately distinct:
 *   · not an error            — "No findings — clean." (unchanged)
 *   · an error WITH a reason  — say what actually happened
 *   · an error with NO reason — say that the reason was not recorded, and do NOT fall back to
 *                               "unreadable". A guess dressed as a finding is worse than a gap,
 *                               and this is the exact sentence that misdirected a whole
 *                               investigation once already.
 */
export function noFindingsLine(status, reason) {
  if (status !== 'unanalysable') return 'No findings — clean.'
  // "Could not process" rather than "could not analyse": the failure may have happened before the
  // file was ever opened, and the record cannot tell the two apart on its own.
  return reason
    ? `Could not process this file — ${reason}`
    : 'Could not process this file. No reason was recorded for this scan, so what failed '
      + '(fetch or analysis) is not known from the record.'
}

/**
 * Is the recorded reason likely to be about the SOURCE rather than the document?
 *
 * Used only to add one orienting clause, never to change the reason itself. It exists because the
 * default reading of "could not process" is "the file is broken" — and when the message names an
 * HTTP failure, that reading sends someone to inspect a document that was never touched.
 */
export function looksLikeFetchFailure(reason) {
  if (!reason) return false
  return /HttpError|HTTPError|404|403|401|timeout|TimeoutException|ConnectError|ReadTimeout|NoneType/i
    .test(reason)
}
