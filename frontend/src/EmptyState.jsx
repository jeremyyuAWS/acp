export default function EmptyState({ onScan, busy, hasDriveToken }) {
  return (
    <div className="empty">
      <div className="emptyicon" aria-hidden="true">◎</div>
      <h3 className="emptytitle">Start here — connect a source &amp; scan</h3>
      <p className="muted emptysub">ACP inventories your documents, scores each one against WCAG 2.1 AA, and guides you through fixing every finding — all in one workflow.</p>
      <div className="onboarding-steps" role="list" aria-label="How it works">
        <div className="onboarding-step" role="listitem">
          <div className="onboarding-step-n" aria-hidden="true">1</div>
          <div className="onboarding-step-title">Discover</div>
          <div className="onboarding-step-desc">Connect Google Drive or SharePoint. ACP crawls metadata, classifies documents, and flags risk.</div>
        </div>
        <div className="onboarding-step" role="listitem">
          <div className="onboarding-step-n" aria-hidden="true">2</div>
          <div className="onboarding-step-title">Assess</div>
          <div className="onboarding-step-desc">Every file is scored 0–100 against WCAG 2.1 AA. Findings are ranked by severity and business exposure.</div>
        </div>
        <div className="onboarding-step" role="listitem">
          <div className="onboarding-step-n" aria-hidden="true">3</div>
          <div className="onboarding-step-title">Remediate</div>
          <div className="onboarding-step-desc">Auto-fix what the engine can; route the rest through human review. Fixed copies write back to Drive.</div>
        </div>
      </div>
      <div className="emptyactions">
        {hasDriveToken
          ? <button disabled={busy} onClick={() => onScan('drive')}>{busy ? 'scanning…' : '→ Scan Google Drive'}</button>
          : <button disabled={busy} onClick={() => onScan('local')}>{busy ? 'scanning…' : '→ Try the sample corpus'}</button>}
        {hasDriveToken && <button className="ghost" disabled={busy} onClick={() => onScan('local')}>Try sample corpus</button>}
      </div>
    </div>
  )
}

export function Loading() {
  return <div className="loadingbox"><span className="spinner" />Loading your workspace…</div>
}
