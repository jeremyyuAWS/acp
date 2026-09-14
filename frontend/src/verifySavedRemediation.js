// Read the authoritative current artifact immediately before the hash-bound
// request. No UI draft, delivery receipt digest, or original scan is substituted.
export async function verifySavedRemediation({ runId, item, canAct, getReleaseStatus, getScan, verifySavedCopy }) {
  const assertCurrent = () => {
    if (!canAct() || !runId || item.scanId && item.scanId !== runId) throw new Error('This saved copy is not available for verification in the current run.')
  }
  assertCurrent()
  const status = await getReleaseStatus(runId)
  let record = status.documents?.find(record => record.file === item.file)
  if (!record?.corrected_sha256 || !record.remediated_at) {
    // A corrected artifact can exist before publication is planned. Fetch the
    // owner-scoped scan afresh; never use a cached UI item or delivery digest.
    assertCurrent()
    const scan = await getScan(runId)
    assertCurrent()
    if (scan?.run?.id !== runId) throw new Error('This saved copy is not available for verification in the current run.')
    const matches = scan.files?.filter(record => record.file === item.file) || []
    record = matches.length === 1 ? matches[0] : null
  }
  if (!record?.corrected_sha256 || !record.remediated_at) throw new Error('The saved copy version is unavailable. Refresh the saved result before retrying.')
  assertCurrent()
  const result = await verifySavedCopy(runId, { file: item.file, corrected_sha256: record.corrected_sha256, remediated_at: record.remediated_at })
  assertCurrent()
  return result.corrected_copy_assessment
}
