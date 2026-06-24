export default function EmptyState({ onScan, busy, hasDriveToken }) {
  return (
    <div className="empty">
      <div className="emptyicon" aria-hidden="true">◎</div>
      <h3 className="emptytitle">No scan yet</h3>
      <p className="muted emptysub">Connect a source and run a scan to inventory your documents and score them against WCAG 2.1 AA — findings, status, and the audit trail populate here.</p>
      <div className="emptyactions">
        {hasDriveToken
          ? <button disabled={busy} onClick={() => onScan('drive')}>{busy ? 'scanning…' : 'Scan Google Drive'}</button>
          : <button disabled={busy} onClick={() => onScan('local')}>{busy ? 'scanning…' : 'Try the sample corpus'}</button>}
        {hasDriveToken && <button className="ghost" disabled={busy} onClick={() => onScan('local')}>Try the sample corpus</button>}
      </div>
    </div>
  )
}

export function Loading() {
  return <div className="loadingbox"><span className="spinner" />Loading your workspace…</div>
}
