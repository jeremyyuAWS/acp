import { useThroughput } from './useThroughput.js'
import LiveThroughput from './LiveThroughput.jsx'

const n = (value) => Number(value || 0).toLocaleString()

function Metric({ label, value, delta, displayValue }) {
  return (
    <div className="rem-live-metric">
      <span className="muted">{label}</span>
      <strong>{displayValue ?? n(value)}</strong>
      {delta > 0 && <span className="rem-live-delta" aria-label={`${n(delta)} newly reported`}>+{n(delta)}</span>}
    </div>
  )
}

function Step({ status, label, detail, sublines = [] }) {
  const icon = status === 'done' ? '✓' : status === 'active' ? null : '·'
  return (
    <div role="listitem">
      <div style={{ display: 'grid', gridTemplateColumns: '18px minmax(0,1fr) auto', gap: 8,
                    alignItems: 'center', minHeight: 22 }}>
        <span aria-hidden="true" style={{ color: status === 'done' ? 'var(--success-fg)' : 'var(--muted)',
                                          fontWeight: 700, textAlign: 'center' }}>
          {status === 'active' ? <span className="pulsedot" /> : icon}
        </span>
        <span style={{ fontSize: 13.5 }}>{label}</span>
        {detail && <span className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums',
                                                     textAlign: 'right' }}>{detail}</span>}
      </div>
      {sublines.length > 0 && (
        <ul style={{ margin: '4px 0 1px 26px', paddingLeft: 16, color: 'var(--muted)',
                     fontSize: 12.5, lineHeight: 1.55 }}>
          {sublines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
    </div>
  )
}

export default function RemediationRunProgress({ progress, updateMode = 'idle', runId = 'remediation' }) {
  const totalForRate = Math.max(0, Number(progress?.total || 0))
  const doneForRate = Math.max(0, Number(progress?.done || 0))
  const throughput = useThroughput(runId, doneForRate, Math.max(0, totalForRate - doneForRate))
  if (!progress) return null
  const total = Math.max(0, Number(progress.total || 0))
  const done = Math.min(total, Math.max(0, Number(progress.done || 0)))
  const failed = Math.max(0, Number(progress.failed || 0))
  const finished = total > 0 && done >= total
  const activity = progress.activity || null
  const metrics = progress.metrics || {}
  const workers = progress.workers || {}
  const workerCapacity = Math.max(0, Number(workers.capacity || 0))
  const activeWorkers = Math.max(0, Number(workers.active ?? progress.running ?? activity?.in_flight ?? 0))
  const standbyWorkers = workerCapacity ? Math.max(0, workerCapacity - activeWorkers) : null
  const recent = (progress.history || []).filter((item, index, rows) =>
    item?.text && rows.findIndex((other) => other?.text === item.text) === index).slice(0, 4)

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
                                        background: 'var(--green-bg,#f0f7e6)', color: 'var(--success-fg)',
                                        border: '1px solid var(--green-line,#a8cf7a)' }}>
            {!finished && <span className="pulsedot" aria-hidden="true" />}
            {finished ? 'complete' : updateMode === 'live' ? 'live' : 'updating'}
          </span>
        </div>

        <progress value={done} max={Math.max(1, total)}
                  aria-label={`Automated remediation: ${n(done)} of ${n(total)} documents complete`}
                  aria-valuetext={`${n(done)} of ${n(total)} documents complete`}
                  style={{ width: '100%', height: 7, display: 'block', marginBottom: 12 }} />

        <div className="rem-live-metrics" aria-label="Live remediation totals">
          <Metric label="Documents" value={done} displayValue={`${n(done)} / ${n(total)}`} delta={progress.deltas?.stored} />
          <Metric label="Fixes applied" value={metrics.fixes} delta={progress.deltas?.fixes} />
          <Metric label="Verified" value={metrics.verified} delta={progress.deltas?.verified} />
          <Metric label="Corrected copies" value={metrics.stored} delta={progress.deltas?.stored} />
          <Metric label="Failed" value={metrics.failed ?? failed} delta={progress.deltas?.failed} />
        </div>

        <div role="list" aria-live="polite" aria-atomic="false"
             style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <Step status="done" label="Remediation work queued" detail={`${n(total)} documents`} />
          <Step status={finished ? 'done' : 'active'} label="Applied approved automatic fixes"
                detail={`${n(done)} of ${n(total)} complete`}
                sublines={!finished && activity?.text ? [activity.text] : []} />
          <Step status={finished ? 'done' : done > 0 ? 'active' : 'pending'} label="Re-checked corrected documents"
                detail={(metrics.verified ?? done) > 0 ? `${n(metrics.verified ?? done)} verified` : 'Waiting for first result'} />
          <Step status={finished ? 'done' : done > 0 ? 'active' : 'pending'} label="Recorded corrected copies"
                detail={metrics.stored > 0 ? `${n(metrics.stored)} saved` : progress.latest ? `Latest: ${progress.latest}` : 'Waiting for first result'} />
        </div>

        {(progress.byRule || []).length > 0 && (
          <div className="rem-rule-progress" aria-label="Verified fixes by WCAG criterion">
            {(progress.byRule || []).map((item) => (
              <span className="fmtchip" key={item.rule}>WCAG {item.rule} · {n(item.fixes)} fixes</span>
            ))}
          </div>
        )}

        {!finished && activity?.text && (
          <div style={{ borderTop: '1px solid var(--line,#e4e8ec)', paddingTop: 10, marginTop: 12,
                        fontSize: 12.5, lineHeight: 1.5 }}>
            <div className="muted" style={{ marginBottom: 4 }}>Processing now</div>
            {activity.file && <strong style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{activity.file}</strong>}
            <div aria-live="polite" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
              {activity.sc && <span className="fmtchip">WCAG {activity.sc}{activity.sc_name ? ` · ${activity.sc_name}` : ''}</span>}
              {activity.action && <span>{activity.action}</span>}
              {activity.detail && <span className="muted">· {activity.detail}</span>}
              {activity.in_flight > 1 && <span className="muted">· {n(activity.in_flight)} files in parallel</span>}
            </div>
            <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
              <li>{n(Math.max(0, total - done))} document{total - done === 1 ? '' : 's'} remaining</li>
            </ul>
          </div>
        )}

        {!finished && (activeWorkers > 0 || workerCapacity > 0 || progress.queued > 0) && (
          <div className="rem-worker-line" aria-label="Remediation worker activity">
            <span><span className="pulsedot" aria-hidden="true" /> {n(activeWorkers)} active</span>
            {standbyWorkers != null && <span>{n(standbyWorkers)} standby</span>}
            <span>{n(progress.queued)} queued</span>
            {workerCapacity > 0 && <span>{Math.round((activeWorkers / workerCapacity) * 100)}% utilization</span>}
          </div>
        )}

        {!finished && (recent.length > 1 || (progress.recentFiles || []).length > 0) && (
          <details style={{ borderTop: '1px solid var(--line,#e4e8ec)', paddingTop: 9, marginTop: 10 }}>
            <summary style={{ cursor: 'pointer', fontSize: 12.5, fontWeight: 600 }}>
              Recent remediation activity
            </summary>
            <ul style={{ margin: '8px 0 0', paddingLeft: 20, fontSize: 12.5, lineHeight: 1.55 }}>
              {(progress.recentFiles || []).map((item) => (
                <li key={`${item.at}-${item.file}`}>
                  <time dateTime={item.at}>{item.at ? new Date(item.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}</time>
                  {' '}✓ {item.file} saved
                </li>
              ))}
              {recent.map((item, index) => <li key={`${item.at || index}-${item.text}`}>{item.text}</li>)}
            </ul>
          </details>
        )}

        <div style={{ borderTop: '1px solid var(--line,#e4e8ec)', paddingTop: 10, marginTop: 12 }}>
          <LiveThroughput points={throughput.points} ratePerMin={throughput.ratePerMin}
                          label="Remediation throughput" unitLabel="processed" />
        </div>

        {finished && (
          <p style={{ margin: '12px 0 0', fontSize: 12.5 }}>
            <strong>{n(done - failed)} documents remediated and verified.</strong>{' '}
            {failed ? `${n(failed)} routed for attention.` : 'Corrected copies are ready for review and release.'}
          </p>
        )}
        {failed > 0 && (
          <p role="alert" style={{ fontSize: 12.5, margin: '12px 0 0', color: 'var(--red,#b91c1c)' }}>
            {n(failed)} document{failed === 1 ? '' : 's'} could not be remediated
            {finished ? ' and will require attention.' : '; the remaining work is continuing.'}
          </p>
        )}
      </div>
    </section>
  )
}
