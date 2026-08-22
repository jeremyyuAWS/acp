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
 * Map a raw backend error string to a human-readable message a non-technical user can act on.
 *
 * The backend logs the raw Python exception string, e.g. `HttpError: <HttpError 404 when
 * requesting …>`. That string is useful for debugging (kept in a `title` attribute by the
 * caller) but not for a user who needs to know what went wrong and what they can do about it.
 *
 * Every branch is a bucket — multiple shapes collapse to one sentence. The fallback fires for
 * anything that does not match a known pattern, which keeps the message honest: "could not open"
 * is the right claim when the reason is there but not yet categorised.
 *
 * `null` in → `null` out: the caller decides what to render when there is no recorded reason.
 */
export function friendlyFileError(err) {
  if (!err) return null
  const s = String(err).toLowerCase()
  if (s.includes('404') || s.includes('not found') || s.includes('notfound'))
    return 'File not found — it may have been moved or deleted'
  if (s.includes('403') || s.includes('forbidden') || s.includes('permission'))
    return 'Permission denied — check sharing settings for this file'
  if (s.includes('401') || s.includes('unauthorized'))
    return 'Authentication expired — try reconnecting your account'
  if (s.includes('429') || s.includes('rate limit') || s.includes('quota'))
    return 'Rate limited by the file provider — the file was skipped'
  if (s.includes('timeout') || s.includes('timed out'))
    return 'Request timed out — the file may be too large or the connection was slow'
  if (s.includes('password') || s.includes('encrypted'))
    return 'File is password-protected and could not be opened'
  if (s.includes('corrupt') || s.includes('invalid') || s.includes('parse'))
    return 'File appears to be corrupted or in an unsupported format'
  if (s.includes('too large') || s.includes('size'))
    return 'File exceeds the maximum supported size'
  if (s.includes('unsupported') || s.includes('mime') || s.includes('type'))
    return 'File type is not supported for assessment'
  return 'Could not open this file — it was skipped during assessment'
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
