import { useEffect, useState, useCallback } from 'react'
import Drawer from './Drawer.jsx'
import { getFileTraceData } from './api.js'

// In-app Langfuse trace viewer. Renders a file's trace INSIDE ACP — score, PII,
// remediation and the Discover→Assess→Remediate timeline — from a PHI-safe payload the
// backend fetches with its own keys (scans.py: /trace/file/{file}/data). This exists
// because Langfuse's own trace page hangs for a logged-out visitor on our self-hosted v3
// and sends X-Frame-Options: SAMEORIGIN, so it can be neither linked-to nor iframed.
// The payload never carries document content or the trace name (which held an operator
// email) — see lf.fetch_trace.

// ISO start/end → "1.2s" / "340ms" / "" when either is missing.
function duration(start, end) {
  if (!start || !end) return ''
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (!Number.isFinite(ms) || ms < 0) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

const LEVEL_CLASS = { ERROR: 'tp-lvl-error', WARNING: 'tp-lvl-warn' }

// The result shape is exactly what lf.file_assessment_result writes as the trace OUTPUT:
//   { score, conformant, level, checks_failed, failing_criteria: {SC: count},
//     findings_total, checks?: {PASS/FAIL/REVIEW/NOT_EVALUATED: count},
//     pii?: {flagged, types: [category…], findings, critical}, remediation?: {…booleans} }
// failing_criteria is a DICT keyed by WCAG SC (with finding counts) and pii.types is a LIST of
// category names — never a value. Rendered to match that, not an assumed array/object.
function ResultSummary({ result }) {
  if (!result) return <div className="muted" style={{ marginTop: 8 }}>No assessment recorded on this trace yet.</div>
  const { score, conformant, level, failing_criteria: fc, pii, remediation: rem } = result
  const failing = fc && typeof fc === 'object' ? Object.entries(fc) : []
  const piiTypes = pii && Array.isArray(pii.types) ? pii.types : []
  return (
    <div className="tp-summary">
      <div className="tp-metrics">
        {typeof score === 'number' && (
          <div className="tp-metric"><div className="tp-metric-v">{Math.round(score)}</div><div className="tp-metric-k">score / 100</div></div>
        )}
        <div className="tp-metric">
          <div className="tp-metric-v">{conformant ? '✓' : '✗'}</div>
          <div className="tp-metric-k">{level ? `${level} conformant` : 'conformant'}</div>
        </div>
      </div>
      {failing.length > 0 && (
        <div className="tp-row">
          <div className="tp-row-k">Failing criteria</div>
          <div className="tp-chips">{failing.map(([sc, n]) => (
            <span key={sc} className="tp-chip tp-chip-fail">{sc}{n ? ` ·${n}` : ''}</span>
          ))}</div>
        </div>
      )}
      {pii && pii.flagged && (
        <div className="tp-row">
          <div className="tp-row-k">Sensitive data{pii.critical ? ' (critical)' : ''}</div>
          <div className="tp-chips">
            {piiTypes.length
              ? piiTypes.map((t) => <span key={t} className="tp-chip tp-chip-pii">{t}</span>)
              : <span className="tp-chip tp-chip-pii">{pii.findings ? `${pii.findings} finding${pii.findings === 1 ? '' : 's'}` : 'present'}</span>}
          </div>
        </div>
      )}
      {rem && (
        <div className="tp-row">
          <div className="tp-row-k">Remediation</div>
          <div className="tp-chips">
            <span className={`tp-chip ${rem.remediated ? 'tp-chip-ok' : 'tp-chip-muted'}`}>{rem.remediated ? 'remediated' : 'not remediated'}</span>
            {rem.written_back && <span className="tp-chip tp-chip-ok">written back</span>}
            {rem.published && <span className="tp-chip tp-chip-ok">published</span>}
          </div>
        </div>
      )}
    </div>
  )
}

function Timeline({ observations }) {
  const obs = observations || []
  if (!obs.length) return <div className="muted" style={{ marginTop: 8 }}>No spans recorded.</div>
  return (
    <ol className="tp-timeline">
      {obs.map((o, i) => {
        const isGen = String(o.type || '').toUpperCase() === 'GENERATION'
        const dur = duration(o.start, o.end)
        return (
          <li key={i} className={`tp-obs ${LEVEL_CLASS[String(o.level || '').toUpperCase()] || ''}`}>
            <div className="tp-obs-head">
              <span className={`tp-badge ${isGen ? 'tp-badge-gen' : 'tp-badge-span'}`}>{isGen ? 'AI' : 'step'}</span>
              <span className="tp-obs-name">{o.name || (isGen ? 'generation' : 'span')}</span>
              {dur && <span className="tp-obs-dur muted">{dur}</span>}
            </div>
            {isGen && (o.model || o.input_tokens != null || o.output_tokens != null || o.cost) && (
              <div className="tp-obs-meta muted">
                {o.model && <span>{o.model}</span>}
                {(o.input_tokens != null || o.output_tokens != null) && <span>{o.input_tokens ?? '?'}→{o.output_tokens ?? '?'} tok</span>}
                {o.cost ? <span>${Number(o.cost).toFixed(4)}</span> : null}
              </div>
            )}
            {o.status && <div className="tp-obs-status muted">{o.status}</div>}
          </li>
        )
      })}
    </ol>
  )
}

export default function TracePanel({ scanId, file, onClose }) {
  const [state, setState] = useState({ loading: true })

  const load = useCallback(() => {
    setState({ loading: true })
    let cancelled = false
    getFileTraceData(scanId, file)
      .then((r) => { if (!cancelled) setState({ loading: false, ...r }) })
      .catch(() => { if (!cancelled) setState({ loading: false, status: 'pending' }) })
    return () => { cancelled = true }
  }, [scanId, file])

  useEffect(() => load(), [load])

  const trace = state.trace
  const title = trace?.document || file || 'Trace'
  const subtitle = trace ? [trace.format, 'observability trace'].filter(Boolean).join(' · ') : 'observability trace'

  return (
    <Drawer title={title} subtitle={subtitle} onClose={onClose}>
      <div className="tp-body">
        {state.loading && <div className="muted">Loading trace…</div>}

        {!state.loading && state.status === 'not_configured' && (
          <div className="muted">Tracing isn’t configured for this deployment, so there’s nothing to show.</div>
        )}

        {!state.loading && state.status === 'pending' && (
          <div>
            <div className="muted">This trace hasn’t finished recording yet — Langfuse ingests asynchronously, so it can take a few seconds.</div>
            <button className="ghost small" style={{ marginTop: 10 }} onClick={load}>Retry</button>
          </div>
        )}

        {!state.loading && state.status === 'ok' && trace && (
          <>
            <ResultSummary result={trace.result} />
            <div className="tp-section-h">Timeline</div>
            <Timeline observations={trace.observations} />
          </>
        )}
      </div>
    </Drawer>
  )
}
