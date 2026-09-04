const count = (value) => Number(value || 0).toLocaleString()

export default function DiscoveryIntegrityRecovery({ integrity, source = 'drive', onReconnect,
  onReviewScope, onRetry, onViewLiveOps }) {
  if (integrity?.status !== 'blocked' || integrity?.code !== 'unexpected_scope_collapse') return null

  const current = Number(integrity.current_count || 0)
  const baseline = Number(integrity.baseline_count || 0)
  const reduction = baseline > 0 ? Math.max(0, Math.round((1 - current / baseline) * 1000) / 10) : null
  const sourceName = source === 'sharepoint' ? 'SharePoint' : 'Google Drive'

  return (
    <section className="discover-integrity-recovery" role="alert"
             aria-labelledby="discovery-integrity-title">
      <div className="discover-integrity-recovery__head">
        <div>
          <div className="eyebrow">DISCOVERY INTEGRITY CHECK</div>
          <h2 id="discovery-integrity-title">Discovery scope changed unexpectedly</h2>
          <p>
            ACP stopped this run before it could replace your last verified inventory. This
            usually means the connected account, permissions, or selected scope changed.
          </p>
        </div>
        <span className="discover-integrity-recovery__badge">Action needed</span>
      </div>

      <div className="discover-integrity-recovery__comparison"
           aria-label={`Previous verified inventory ${count(baseline)} files; current listing ${count(current)} files`}>
        <div>
          <span>Previous verified inventory</span>
          <strong>{count(baseline)}</strong>
          <small>files</small>
        </div>
        <div className="discover-integrity-recovery__arrow" aria-hidden="true">→</div>
        <div>
          <span>Current listing · blocked</span>
          <strong>{count(current)}</strong>
          <small>{reduction == null ? 'files' : `files · ${reduction}% fewer`}</small>
        </div>
      </div>

      <ul>
        <li>Your last verified inventory remains unchanged.</li>
        <li>No documents were assessed, remediated, or written back.</li>
        <li>Reconnect {sourceName} or confirm the intended scope, then run Discovery again.</li>
      </ul>

      <div className="discover-integrity-recovery__actions">
        {onReconnect && <button type="button" className="primary small" onClick={onReconnect}>
          Reconnect {sourceName}
        </button>}
        {onReviewScope && <button type="button" className="ghost small" onClick={onReviewScope}>
          Review scan scope
        </button>}
        {onRetry && <button type="button" className="ghost small" onClick={onRetry}>
          Run Discovery again
        </button>}
        {onViewLiveOps && <button type="button" className="linkbtn" onClick={onViewLiveOps}>
          View in Live Operations →
        </button>}
      </div>
      {integrity.baseline_scan_id && (
        <div className="discover-integrity-recovery__reference">
          Compared with verified scan <code>{integrity.baseline_scan_id}</code>
        </div>
      )}
    </section>
  )
}
