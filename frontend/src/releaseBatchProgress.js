// Approved batch scope is separate from the latest incremental delivery request.
export function releaseBatchProgress(snapshot) {
  const batch = snapshot?.release_batch_progress
  if (snapshot?.stage !== 'release' || !batch || (batch.available !== true && batch.scope === 'manual')) return null
  const unavailable = () => ({available:false,state:'failed',label:'Delivery confirmation unavailable',
    summary:'Approved batch delivery not confirmed'})
  const count = value => Number.isSafeInteger(value) && value >= 0
  if (snapshot?.stage !== 'release' || batch?.available !== true
      || !batch.authorization_id || !batch.run_id || !count(batch.total) || batch.total === 0
      || !count(batch.delivered) || !count(batch.remaining)
      || batch.delivered + batch.remaining !== batch.total) return unavailable()
  const active = ['active', 'waiting', 'processing', 'publishing'].includes(batch.status)
  const settled = batch.remaining === 0 && batch.status === 'completed'
  const state = settled ? snapshot.state : (active ? 'processing' : 'failed')
  const label = settled ? null : active
    ? (batch.remaining > 0 ? 'Publishing automatically' : 'Finalizing automatic release')
    : batch.status === 'stopped' ? 'Automatic delivery stopped' : 'Delivery needs attention'
  return { ...batch, state, label,
    summary: `${batch.delivered.toLocaleString()} of ${batch.total.toLocaleString()} authorized files delivered` }
}
