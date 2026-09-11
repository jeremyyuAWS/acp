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
  const authorization = batchId && releaseState?.scanId === scanId && releaseState.authorization?.run_id === batchId
    ? releaseState.authorization : undefined
  return { batchId, authorization }
}
