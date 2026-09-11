import { useEffect } from 'react'

// A local accepted response is newer than the last streamed snapshot. Keep that
// identity until the stream confirms it, then follow subsequent server executions.
export default function useAcceptedRemediationIdentity({ scanId, snapshot, launch, clearLaunch, releaseState }) {
  const scopedSnapshot = scanId && (snapshot?.scan_id || snapshot?.run_id) === scanId ? snapshot : null
  const pendingLaunch = scanId && launch?.scanId === scanId ? launch : null
  const batchId = pendingLaunch?.batchId || scopedSnapshot?.batch_id || null
  useEffect(() => {
    if (pendingLaunch?.batchId && scopedSnapshot?.batch_id === pendingLaunch.batchId) clearLaunch(null)
  }, [pendingLaunch?.batchId, scopedSnapshot?.batch_id, clearLaunch])
  const sameReleaseRun = batchId && releaseState?.scanId === scanId
  const authorization = sameReleaseRun && releaseState.authorization?.run_id === batchId
    ? releaseState.authorization
    : sameReleaseRun && releaseState.runId === batchId && releaseState.authorization === null
      ? { run_id: batchId, allow_remaining_issues: false } : undefined
  return { batchId, authorization }
}
