// Read the authoritative current artifact immediately before the hash-bound
// request. No UI draft, delivery receipt digest, or original scan is substituted.
export async function verifySavedRemediation({ runId, item, canAct, getReleaseStatus, verifySavedCopy }) {
  const assertCurrent = () => {
    if (!canAct() || !runId || item.scanId && item.scanId !== runId) throw new Error('This saved copy is not available for verification in the current run.')
  }
  assertCurrent()
  const status = await getReleaseStatus(runId)
  const record = status.documents?.find(record => record.file === item.file)
  if (!record?.corrected_sha256 || !record.remediated_at) throw new Error('The saved copy version is unavailable. Refresh the saved result before retrying.')
  assertCurrent()
  const result = await verifySavedCopy(runId, { file: item.file, corrected_sha256: record.corrected_sha256, remediated_at: record.remediated_at })
  assertCurrent()
  return result.corrected_copy_assessment
}
