// Delivery and outcome accounting can keep the shared stream open after document work drains.
export function remediationWorkRunning(snapshot, batchId, busy, progress) {
  const fallback = !!busy || !!(progress && progress.done < progress.total)
  if (!batchId || snapshot?.batch_id !== batchId) return fallback
  const counts = snapshot.documents
  const total = snapshot.total_documents
  const keys = ['completed', 'processing', 'waiting', 'review', 'failed', 'skipped']
  if (!Number.isSafeInteger(total) || total <= 0 || !counts
    || keys.some(key => !Number.isSafeInteger(counts[key]) || counts[key] < 0)
    || keys.reduce((sum, key) => sum + counts[key], 0) !== total) return fallback
  return counts.processing > 0 || counts.waiting > 0
}
