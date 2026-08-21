// WHY the files in the "could not be read" bucket could not be read.
//
// Discover's unreadable count has always been derivable — `status === 'error'`, one bucket. The
// REASON was not on this screen at all. It was recorded the whole time, per file, by handlers:
//
//     log_decision("system", "scan.file_error", scan_id=…, file=name,
//                  detail=f"{type(e).__name__}: {e}"[:200])
//
// and `GET /decisions?scan_id=…` returns it. FileDrawer already reads that log to explain ONE
// document (fileErrorReason.js). Nothing aggregated it, so a run with 18 unreadable files out of 22
// could only be explained by opening 18 drawers — and `discoveryRecommendations.defaultReasonOf`
// reads `openIssue` / `error_reason` / `errorReason`, none of which the backend puts on a file row,
// so the breakdown that exists rendered "No reason was recorded for these" over a fully recorded
// scan.
//
// THE BUCKETING IS THE WHOLE POINT, and it is the part that has to be derived rather than guessed.
// The verbatim detail carries a URL, an item id or a path, so grouping on it yields one bucket per
// file — a list, not a breakdown. So a bucket is the exception TYPE plus an HTTP status when the
// message states one, both lifted out of the recorded string. Nothing is inferred about the cause:
// an unparseable detail keeps its verbatim text as its own bucket, and a file with no logged row
// stays in "not recorded", which is a gap and must keep looking like one.

import { defaultReasonOf } from './discoveryRecommendations.js'
import { errorReasonFor, looksLikeFetchFailure } from './fileErrorReason.js'

/** `Type: message` → `Type`. The logger's own format, so this is reading the record, not parsing
 *  prose. Anything that does not match that shape yields null and the detail is kept verbatim. */
export function exceptionType(detail) {
  const m = /^\s*([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Timeout|Failure))\s*:/.exec(String(detail || ''))
  return m ? m[1] : null
}

/** The HTTP status the message states, or null. Only 4xx/5xx, and only where the text says it is a
 *  status — a bare "404" inside a filename is not a status, so a digit run on its own is ignored. */
export function httpStatus(detail) {
  const s = String(detail || '')
  const m = /(?:HttpError|HTTPError|status(?:\s*code)?|returned|responded(?:\s*with)?)\D{0,12}\b([45]\d\d)\b/i.exec(s)
  return m ? Number(m[1]) : null
}

/**
 * One bucket label for one recorded detail.
 *
 * Deliberately NOT a human explanation of the failure. "HttpError · HTTP 404" is a restatement of
 * what was logged; "the file was deleted from SharePoint" would be a diagnosis, and this codebase
 * has already spent one whole investigation on a sentence that diagnosed instead of reporting.
 */
export function bucketLabel(detail) {
  const text = String(detail || '').trim()
  if (!text) return null
  const type = exceptionType(text)
  const status = httpStatus(text)
  if (!type) return text                       // unrecognised shape → verbatim, never dropped
  return status ? `${type} · HTTP ${status}` : type
}

/**
 * Build the `reasonOf` DiscoveryResults takes, from a scan's decision log.
 *
 * Precedence is row field first, decision log second. The row field is what a future backend would
 * put on the record itself; falling back the other way would let a stale log outrank it.
 *
 * Returns `{ reasonOf, sampleOf, fetchLikely }`:
 *   · reasonOf(row)   the bucket label, or null when nothing was recorded for that file
 *   · sampleOf(label) the first verbatim detail seen in that bucket — the reader's way back to the
 *                     actual message, since the label is a summary of it
 *   · fetchLikely(label)  the recorded message names a transport/HTTP failure, so the file may
 *                     never have been fetched at all. ONE orienting clause, never a re-diagnosis:
 *                     "could not be read" reads as "the document is broken", and that reading sends
 *                     someone to inspect a document nothing ever touched.
 */
export function buildUnreadableWhy(decisions, files = null) {
  const samples = new Map()
  const fetchy = new Map()
  const record = (detail, label) => {
    if (!label || samples.has(label)) return
    samples.set(label, String(detail))
    fetchy.set(label, looksLikeFetchFailure(detail))
  }
  const reasonOf = (row) => {
    const detail = defaultReasonOf(row) || errorReasonFor(decisions, row && row.file)
    const label = bucketLabel(detail)
    record(detail, label)
    return label
  }
  // Walked EAGERLY when the rows are to hand, so `sampleOf` does not depend on `reasonOf` having
  // been called first. A lookup that silently returns null until some other function has run is
  // the kind of order coupling that survives every test and fails once, in a component that
  // reorders its own render.
  if (Array.isArray(files)) files.forEach(reasonOf)
  return {
    reasonOf,
    sampleOf: (label) => samples.get(label) || null,
    fetchLikely: (label) => !!fetchy.get(label),
  }
}
