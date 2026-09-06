import React from 'react'

export default function DiscoveryContinuityChoice({ choice, onContinue, onReplace, onDismiss }) {
  if (!choice) return null
  return (
    <section className="panel" role="alertdialog" aria-labelledby="discovery-continuity-title"
             aria-describedby="discovery-continuity-copy"
             style={{ marginBottom: 12, borderLeft: '4px solid var(--accent, #6D28D9)', background: 'var(--surface)' }}>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 420px' }}>
          <strong id="discovery-continuity-title">Discovery is already running</strong>
          <div id="discovery-continuity-copy" className="muted" style={{ marginTop: 3, fontSize: 12.5 }}>
            Continue the current workflow to keep its progress. Start a new revision only if you
            intend to stop and replace it with a separate Discovery.
          </div>
          <div className="muted" style={{ marginTop: 5, fontSize: 11.5, fontFamily: 'monospace' }}>
            Scan {choice.scanId}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" onClick={onContinue}>Continue current Discovery</button>
          <button type="button" className="secondary" onClick={onReplace}>Start revised Discovery</button>
          <button type="button" className="ghost small" onClick={onDismiss}>Keep current screen</button>
        </div>
      </div>
    </section>
  )
}
