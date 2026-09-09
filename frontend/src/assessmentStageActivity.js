/** Presentation shared with the runner. Coordinator completion alone is not document completion. */
export function assessmentStageActivity(snapshot, activity, scanId) {
  if (snapshot?.stage !== 'assess') return null
  // Completed local state only belongs to the execution returned by its own start request.
  // Legacy saved state without identity can conservatively show activity, never completion.
  const live = activity && activity.runId === (snapshot.scan_id || scanId)
    && (activity.executionId ? activity.executionId === snapshot.execution_id : activity.phase !== 'done')
    && ['starting', 'running', 'done'].includes(activity.phase) ? activity : null
  const buckets = snapshot.domain_reconciliation?.buckets || {}
  const pending = (buckets.waiting || 0) + (buckets.processing || 0)
  // Preserve durable failures and cancellation; a local running callback cannot erase them.
  if (['failed', 'cancelled', 'superseded', 'integrity_failed'].includes(snapshot.state)) return null
  if (live && (live.phase !== 'done' || ['succeeded', 'processing_complete'].includes(snapshot.state))) return {
    state: live.phase === 'done' ? 'succeeded' : 'processing',
    label: live.phase === 'done' ? 'Complete' : live.phase === 'starting' ? 'Starting' : 'Assessing',
    count: `${live.completed} assessed of ${live.total} eligible documents`,
  }
  if (pending > 0 && ['succeeded', 'processing_complete'].includes(snapshot.state)) {
    return { state: 'processing', label: 'Assessing' }
  }
  return null
}
