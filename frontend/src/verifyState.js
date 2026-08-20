// R9 — what has actually been VERIFIED, as opposed to what has been attempted.
//
// A FIX IS A CLAIM UNTIL A RE-RUN CONFIRMS IT. Applying a fix and clearing a finding are two
// different events, and the gap between them is not theoretical in this codebase: several criteria
// (docx and pdf language and title among them) report "applied" and do not clear, because the fixer
// writes one metadata field and the detector reads another. That is precisely why `remediate_file`
// re-scans the corrected bytes before crediting anything, and why this module partitions findings
// by the RE-SCAN's answer rather than by whether a batch ran.
//
// So there are three states here and only one of them is good news:
//
//   confirmed    the criterion was re-scanned in the corrected copy and no longer appears there.
//   unconfirmed  a remediation ran on this document and this criterion did not come back clear —
//                the fix did not take, or was never attempted. It is still a finding.
//   untouched    no remediation has run on this document at all.
//
// Nothing in here ever reports the second or third as resolved, and there is no state meaning "we
// applied something so it is probably fine". The absence of that state is the module.
//
// WHAT "CONFIRMED" IS EVIDENCE ABOUT, AND IT IS NOT THE ORIGINAL. The re-scan reads the corrected
// COPY. The source document is unchanged and still contains the finding; ACP does not modify it.
// The screen has to say that, because "1.3.1 confirmed cleared" beside a filename reads as a claim
// about the file that filename names.
import { documentRows } from './assessMetrics.js'
import { criteriaNamed } from './remediationWork.js'

/** The latest `updated_at` among a document's completed remediation-state rows, or null. */
export function verifiedAtOf(entries) {
  let latest = null
  for (const e of entries || []) {
    if (!e || typeof e === 'string') continue
    if ('state' in e && e.state !== 'complete') continue
    const at = e.updated_at || e.updatedAt || null
    if (at && (!latest || String(at) > String(latest))) latest = String(at)
  }
  return latest
}

/**
 * Whether a remediation run has produced a corrected copy of this document.
 *
 * Read off the file record the backend already sends: `record_remediation` writes `blob_url` (the
 * durable copy, always) and `drive_write_url` (the mirror, when enabled), and `remediated_at` is
 * the timestamp. Any one of them is a run having happened.
 */
export const wasRemediated = (f) =>
  !!(f && (f.remediated_at || f.drive_write_url || f.blob_url))

/**
 * The verification state of an estate.
 *
 * Returns `null` when nothing has been loaded. As everywhere else on these screens, an absent run
 * is not a run that verified nothing.
 *
 * @param files            the scan's file rows — the same array the assessment screen was given
 * @param cap              remediation-capability map
 * @param assessment       assessment-lane map
 * @param criteria         the agreed criteria
 * @param level            conformance target
 * @param appliedCriteria  {[file]: rows} from GET /scans/{id}/files/{file}/remediation-state.
 *                         Rows whose `state` is not 'complete' are dropped by `criteriaNamed` —
 *                         a criterion is confirmed only where the backend's own re-scan of the
 *                         corrected bytes found it absent.
 */
export function verifyState(files, { cap, assessment, criteria, level = 'AA',
                                     appliedCriteria = {} } = {}) {
  const all = documentRows(files, { cap, assessment, criteria, level })
  if (!all) return null

  const raw = new Map()
  for (const f of files) raw.set(f.file || f.name || '', f)

  const documents = []
  let confirmedFindings = 0, unconfirmedFindings = 0, untouchedFindings = 0, totalFindings = 0

  for (const row of all) {
    if (!row.opened) continue
    const entries = appliedCriteria[row.file]
    const confirmed = criteriaNamed(entries)
    const remediated = wasRemediated(raw.get(row.file)) || confirmed.size > 0

    const confirmedCriteria = new Set()
    const openCriteria = new Set()
    let nConfirmed = 0
    for (const f of row.findings) {
      if (confirmed.has(f.sc)) { nConfirmed++; confirmedCriteria.add(f.sc) } else openCriteria.add(f.sc)
    }
    const nOpen = row.totalFindings - nConfirmed

    totalFindings += row.totalFindings
    confirmedFindings += nConfirmed
    if (remediated) unconfirmedFindings += nOpen
    else untouchedFindings += nOpen

    documents.push({
      file: row.file,
      name: row.name,
      remediated,
      verifiedAt: verifiedAtOf(entries),
      totalFindings: row.totalFindings,
      // Named `confirmed` / `open`, never `fixed` / `remaining`. "Fixed" is the word this whole
      // module exists to withhold until a re-scan has earned it.
      confirmed: nConfirmed,
      open: nOpen,
      confirmedCriteria: [...confirmedCriteria].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })),
      openCriteria: [...openCriteria].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })),
    })
  }

  // Documents first by what is still open, so the ones needing another pass sit at the top; a
  // fully-confirmed document is the least urgent row on the screen, whatever its size.
  documents.sort((a, b) => b.open - a.open || a.name.localeCompare(b.name))

  const remediatedDocuments = documents.filter((d) => d.remediated).length

  return {
    documents,
    documentsAssessed: documents.length,
    remediatedDocuments,
    totalFindings,
    confirmedFindings,
    unconfirmedFindings,
    untouchedFindings,
    // The documents a re-scan would be about. Handed out so the caller does not re-derive a
    // different set from the one the screen counted.
    remediatedFiles: documents.filter((d) => d.remediated).map((d) => d.file),
  }
}

/** The identity the panel prints. Same contract as everywhere else on these screens. */
export function reconcileVerify(v) {
  if (!v) return null
  const sum = v.confirmedFindings + v.unconfirmedFindings + v.untouchedFindings
  return {
    ok: sum === v.totalFindings,
    line: `${v.confirmedFindings} confirmed cleared + ${v.unconfirmedFindings} applied but not `
        + `confirmed + ${v.untouchedFindings} not yet remediated = ${v.totalFindings} finding`
        + `${v.totalFindings === 1 ? '' : 's'}`,
    sum,
  }
}
