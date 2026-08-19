// The Release Center's honest description of what a release DOES — kept pure so the wording that
// makes (or breaks) a truthful claim is unit-tested, not buried in JSX. ACP writes a corrected
// COPY; it never overwrites the source, and it never certifies overall conformance. Every string
// here is bounded by those two facts.

// Where a single file's released copy actually lands. A Drive-sourced file (it carries a
// drive_file_id) gets the Drive mirror folder when the platform has that enabled; everything else —
// and every file when the mirror is off — is delivered via the durable Azure Blob copy.
export function releaseDestination({ driveFileId, driveMirrorEnabled, driveMirrorFolder } = {}) {
  const toDrive = !!driveFileId && !!driveMirrorEnabled
  const folder = driveMirrorFolder || 'Remediated'
  return { toDrive, folder, label: toDrive ? `Drive “${folder}” + Blob` : 'Azure Blob' }
}

// The batch destination phrase for the panel and the confirmation modal. `anyDrive` = at least one
// file in the batch is Drive-sourced. Mirror off (or no Drive files) → Blob is the only destination.
export function releaseDestinationPhrase({ anyDrive, driveMirrorEnabled, driveMirrorFolder } = {}) {
  const folder = driveMirrorFolder || 'Remediated'
  return (anyDrive && driveMirrorEnabled)
    ? `the Drive “${folder}” folder and a durable Azure Blob copy`
    : 'a durable Azure Blob copy (a download link)'
}

// The confirmation-modal body: the exact, checkable consequences of releasing. Deliberately never
// says "certify" as a positive claim — only ever to disclaim it.
export function releaseConfirmLines({ count = 0, anyDrive = false, driveMirrorEnabled = false, driveMirrorFolder = 'Remediated' } = {}) {
  const dest = releaseDestinationPhrase({ anyDrive, driveMirrorEnabled, driveMirrorFolder })
  return [
    `ACP writes a corrected copy of ${count === 1 ? 'this document' : `these ${count} documents`} to ${dest}.`,
    'Your original files are never overwritten.',
    'Each release is recorded in the audit trail.',
    'This records that the files were verified against the criteria in scope — it does not certify overall WCAG conformance.',
  ]
}
