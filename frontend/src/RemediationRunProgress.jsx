const n = (value) => Number(value || 0).toLocaleString()

function Step({ status, label, detail }) {
  const icon = status === 'done' ? '✓' : status === 'active' ? null : '·'
  return (
    <div role="listitem" style={{ display: 'grid', gridTemplateColumns: '18px minmax(0,1fr) auto', gap: 8,
                  alignItems: 'center', minHeight: 22 }}>
      <span aria-hidden="true" style={{ color: status === 'done' ? 'var(--green,#3B6D11)' : 'var(--muted)',
                                        fontWeight: 700, textAlign: 'center' }}>
        {status === 'active' ? <span className="pulsedot" /> : icon}
      </span>
      <span style={{ fontSize: 13.5 }}>{label}</span>
      {detail && <span className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums',
                                                   textAlign: 'right' }}>{detail}</span>}
    </div>
  )
}

export default function RemediationRunProgress({ progress, updateMode = 'idle' }) {
  if (!progress) return null
  const total = Math.max(0, Number(progress.total || 0))
  const done = Math.min(total, Math.max(0, Number(progress.done || 0)))
  const failed = Math.max(0, Number(progress.failed || 0))
  const finished = total > 0 && done >= total

  return (
    <section className="discover-run-progress" role="region" aria-label="Automated remediation progress"
             style={{ marginBottom: 14 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '14px 16px', background: 'var(--panel,#fff)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 14.5 }}>Automated remediation</strong>
          <span role="status" style={{ fontSize: 11.5, padding: '2px 7px', borderRadius: 4,
                                        display: 'inline-flex', alignItems: 'center', gap: 5,
                                        background: 'var(--green-bg,#f0f7e6)', color: 'var(--green,#3B6D11)',
                                        border: '1px solid var(--green-line,#a8cf7a)' }}>
            {!finished && <span className="pulsedot" aria-hidden="true" />}
            {finished ? 'complete' : updateMode === 'live' ? 'live' : 'updating'}
          </span>
        </div>

        <progress value={done} max={Math.max(1, total)}
                  aria-label={`Automated remediation: ${n(done)} of ${n(total)} documents complete`}
                  aria-valuetext={`${n(done)} of ${n(total)} documents complete`}
                  style={{ width: '100%', height: 7, display: 'block', marginBottom: 12 }} />

        <div role="list" aria-live="polite" aria-atomic="false"
             style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <Step status="done" label="Remediation work queued" detail={`${n(total)} documents`} />
          <Step status={finished ? 'done' : 'active'} label="Applied approved automatic fixes"
                detail={`${n(done)} of ${n(total)} complete`} />
          <Step status={finished ? 'done' : done > 0 ? 'active' : 'pending'} label="Re-checked corrected documents"
                detail={done > 0 ? `${n(done)} verified` : 'Waiting for first result'} />
          <Step status={finished ? 'done' : done > 0 ? 'active' : 'pending'} label="Recorded corrected copies"
                detail={progress.latest ? `Latest: ${progress.latest}` : 'Waiting for first result'} />
        </div>

        {progress.activity?.text && !finished && (
          <p className="muted" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.5 }}>
            {progress.activity.text}
          </p>
        )}
        {failed > 0 && (
          <p role="alert" style={{ fontSize: 12.5, margin: '12px 0 0', color: 'var(--red,#b91c1c)' }}>
            {n(failed)} document{failed === 1 ? '' : 's'} could not be remediated; the remaining work is continuing.
          </p>
        )}
      </div>
    </section>
  )
}
