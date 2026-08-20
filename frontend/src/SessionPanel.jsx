import { useEffect, useState, useCallback } from 'react'
import Drawer from './Drawer.jsx'
import TracePanel from './TracePanel.jsx'
import { getSessionTraceData, openTraceUrl } from './api.js'

// In-app view of a whole SCAN's session — every file's trace as one list, with a scan-level
// rollup on top. This is the aggregate that hung Langfuse's own UI on large scans (the reason
// for the v2→v3 move); rendered here it's a plain capped list ACP controls, and clicking any row
// drills into that file's full trace (TracePanel). The payload is PHI-safe: document labels are
// redacted, PII shows as type categories only, and the operator email never rides along.

function Stat({ v, k }) {
  return <div className="tp-metric"><div className="tp-metric-v">{v}</div><div className="tp-metric-k">{k}</div></div>
}

function Rollup({ r }) {
  if (!r) return null
  return (
    <div className="tp-metrics" style={{ flexWrap: 'wrap', gap: 18 }}>
      <Stat v={r.documents} k="documents" />
      <Stat v={r.assessed} k="assessed" />
      <Stat v={r.conformant} k="conformant" />
      {typeof r.avg_score === 'number' && <Stat v={Math.round(r.avg_score)} k="avg score" />}
      <Stat v={r.with_failures} k="with failures" />
      <Stat v={r.with_pii} k="with PII" />
    </div>
  )
}

function FileRow({ f, onOpen }) {
  const res = f.result
  const failing = res && res.failing_criteria ? Object.keys(res.failing_criteria).length : 0
  const pii = res && res.pii && res.pii.flagged
  return (
    <button type="button" className="sp-row" onClick={onOpen}
            title="Open this document’s full trace">
      <span className="sp-row-doc">{f.document || f.trace_id}</span>
      {f.format && <span className="tp-badge tp-badge-span">{f.format}</span>}
      {res
        ? <>
            {typeof res.score === 'number' && <span className="sp-row-score">{Math.round(res.score)}</span>}
            <span className={res.conformant ? 'sp-row-ok' : 'sp-row-bad'}>{res.conformant ? '✓' : '✗'}</span>
            {failing > 0 && <span className="tp-chip tp-chip-fail">{failing} failing</span>}
            {pii && <span className="tp-chip tp-chip-pii">PII</span>}
          </>
        : <span className="muted" style={{ fontSize: 12 }}>not assessed</span>}
    </button>
  )
}

export default function SessionPanel({ scanId, onClose }) {
  const [state, setState] = useState({ loading: true })
  const [openFile, setOpenFile] = useState(null)

  const load = useCallback(() => {
    setState({ loading: true })
    let cancelled = false
    getSessionTraceData(scanId)
      .then((r) => { if (!cancelled) setState({ loading: false, ...r }) })
      .catch(() => { if (!cancelled) setState({ loading: false, status: 'pending' }) })
    return () => { cancelled = true }
  }, [scanId])

  useEffect(() => load(), [load])

  const sess = state.session
  const subtitle = sess ? `${sess.total} document${sess.total === 1 ? '' : 's'} · observability` : 'observability'

  return (
    <>
      <Drawer title="Scan trace" subtitle={subtitle} onClose={onClose}>
        <div className="tp-body">
          {state.loading && <div className="muted">Loading scan traces…</div>}

          {!state.loading && state.status === 'not_configured' && (
            <div className="muted">Tracing isn’t configured for this deployment, so there’s nothing to show.</div>
          )}

          {!state.loading && state.status === 'pending' && (
            <div>
              <div className="muted">This scan’s traces haven’t finished recording yet — Langfuse ingests asynchronously, so it can take a few seconds.</div>
              <button className="ghost small" style={{ marginTop: 10 }} onClick={load}>Retry</button>
            </div>
          )}

          {!state.loading && state.status === 'ok' && sess && (
            <>
              <Rollup r={sess.rollup} />
              <div className="tp-section-h">Documents</div>
              {sess.files.length === 0
                ? <div className="muted">No file traces in this scan yet.</div>
                : <div className="sp-list">{sess.files.map((f) => (
                    <FileRow key={f.trace_id} f={f} onOpen={() => setOpenFile(f.document)} />
                  ))}</div>}
              {sess.truncated && (
                <div className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                  Showing the first {sess.files.length} of {sess.total} documents (worst-scoring first).
                </div>
              )}
              {/* Advanced: the whole scan's session in Langfuse's own UI (requires a Langfuse
                  login). The in-app rollup above is the no-login primary. */}
              {openTraceUrl(scanId, 'session') && (
                <a className="tp-langfuse-link" href={openTraceUrl(scanId, 'session')}
                   target="_blank" rel="noopener noreferrer"
                   title="Open this scan's session in Langfuse's own UI — requires a Langfuse login">
                  Open in Langfuse ↗ <span className="muted">· advanced</span>
                </a>
              )}
            </>
          )}
        </div>
      </Drawer>
      {openFile && <TracePanel scanId={scanId} file={openFile} onClose={() => setOpenFile(null)} />}
    </>
  )
}
