import { useEffect, useState, useCallback } from 'react'
import Drawer from './Drawer.jsx'
import { getDocumentHistory } from './api.js'

// Drill-in is a callback (onOpenScan) rather than a direct <TracePanel> render on purpose: this
// panel is opened FROM TracePanel, so importing it here would make an import cycle. The parent
// (TracePanel, which can render itself) owns opening the selected scan's trace.

// "This document over time" — one document's trace across EVERY scan it appears in, which
// Langfuse's own session-grouped UI cannot show. A score trajectory + a row per scan, newest
// first, each drilling into that scan's own trace. PHI-safe: the label is an HMAC, no operator
// identity, PII shown only as a count. Fetched from lf.fetch_document_history via the app's proxy.

const fmtDate = (iso) => {
  if (!iso) return ''
  try { return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) }
  catch { return iso.slice(0, 10) }
}

function Trend({ scans }) {
  // scans are newest-first; the trajectory reads oldest→newest left to right.
  const withScore = [...scans].reverse().filter((s) => typeof s.result?.score === 'number')
  if (withScore.length < 2) return null
  const first = withScore[0].result.score
  const last = withScore[withScore.length - 1].result.score
  const delta = Math.round(last - first)
  const dir = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat'
  return (
    <div className="dh-trend">
      <div className="dh-spark">
        {withScore.map((s, i) => (
          <span key={i} className="dh-bar" title={`${fmtDate(s.timestamp)} · ${Math.round(s.result.score)}`}
                style={{ height: `${Math.max(6, Math.round(s.result.score))}%` }} />
        ))}
      </div>
      <div className={`dh-delta dh-delta-${dir}`}>
        {dir === 'up' ? '▲' : dir === 'down' ? '▼' : '■'} {delta > 0 ? '+' : ''}{delta}
        <span className="muted"> since first scan ({withScore.length} scans)</span>
      </div>
    </div>
  )
}

function ScanRow({ s, isCurrent, onOpen }) {
  const r = s.result
  const failing = r && r.failing_criteria ? Object.keys(r.failing_criteria).length : 0
  return (
    <button type="button" className={`sp-row${isCurrent ? ' dh-row-current' : ''}`} onClick={onOpen}
            title="Open this scan's trace for the document">
      <span className="sp-row-doc">{fmtDate(s.timestamp)}{isCurrent ? ' · this scan' : ''}</span>
      {r
        ? <>
            {typeof r.score === 'number' && <span className="sp-row-score">{Math.round(r.score)}</span>}
            <span className={r.conformant ? 'sp-row-ok' : 'sp-row-bad'}>{r.conformant ? '✓' : '✗'}</span>
            {failing > 0 && <span className="tp-chip tp-chip-fail">{failing} failing</span>}
          </>
        : <span className="muted" style={{ fontSize: 12 }}>not assessed</span>}
    </button>
  )
}

export default function DocumentHistoryPanel({ scanId, docLabel, onClose, onOpenScan }) {
  const [state, setState] = useState({ loading: true })

  const load = useCallback(() => {
    setState({ loading: true })
    let cancelled = false
    getDocumentHistory(scanId, docLabel)
      .then((r) => { if (!cancelled) setState({ loading: false, ...r }) })
      .catch(() => { if (!cancelled) setState({ loading: false, status: 'pending' }) })
    return () => { cancelled = true }
  }, [scanId, docLabel])

  useEffect(() => load(), [load])

  const h = state.history
  const subtitle = h ? `${h.total} scan${h.total === 1 ? '' : 's'} · across scans` : 'across scans'

  return (
    <>
      <Drawer title={docLabel || 'Document history'} subtitle={subtitle} onClose={onClose}>
        <div className="tp-body">
          {state.loading && <div className="muted">Loading history…</div>}

          {!state.loading && state.status === 'not_configured' && (
            <div className="muted">Tracing isn’t configured for this deployment, so there’s nothing to show.</div>
          )}

          {!state.loading && state.status === 'pending' && (
            <div>
              <div className="muted">This document’s history hasn’t finished recording yet — try again in a moment.</div>
              <button className="ghost small" style={{ marginTop: 10 }} onClick={load}>Retry</button>
            </div>
          )}

          {!state.loading && state.status === 'ok' && h && (
            <>
              {h.total <= 1
                ? <div className="muted" style={{ marginBottom: 10 }}>Seen in one scan so far — a trajectory appears once this document is scanned again.</div>
                : <Trend scans={h.scans} />}
              <div className="tp-section-h">Scans</div>
              <div className="sp-list">
                {h.scans.map((s) => (
                  <ScanRow key={s.trace_id} s={s} isCurrent={s.scan_id === scanId}
                           onOpen={() => onOpenScan && onOpenScan(s.scan_id)} />
                ))}
              </div>
            </>
          )}
        </div>
      </Drawer>
    </>
  )
}
