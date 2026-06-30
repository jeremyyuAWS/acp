import { useState, useEffect } from 'react'
import { openTraceUrl, getTraceStatus, getScanTraces } from './api.js'

// "📊 View trace" link. File-centric tracing (backend: lf.file_trace) — every file has
// its OWN Langfuse trace (Discover/Assess/Remediate as spans inside it), grouped into a
// session keyed by scan_id:
//   kind='file'    (scanId + file) — that ONE file's full lifecycle trace.
//   kind='session' (scanId only)   — the whole scan's session (every file's trace) — the
//                                     "view this scan" replacement for the old single
//                                     scan/assess/remediate trace.
// Routes through the backend redirect endpoint, which ensures a file trace exists before
// sending you to Langfuse (sessions never need this — they don't 404 when empty).
// Renders nothing when Langfuse isn't configured.
export function TraceChip({ scanId, kind = 'session', file = null, label = 'View trace', title }) {
  const url = openTraceUrl(scanId, kind, file)
  const [available, setAvailable] = useState(null)
  useEffect(() => {
    if (!url) return
    let cancelled = false
    getTraceStatus(scanId, kind, file)
      .then(r => { if (!cancelled) setAvailable(!!r?.available) })
      .catch(() => { if (!cancelled) setAvailable(false) })
    return () => { cancelled = true }
  }, [scanId, kind, file, url])

  if (!url) return null
  if (available === false) return (
    <span className="tracechip tracechip--unavailable"
          title="Trace not available — this scan predates observability wiring">
      📊 {label}
    </span>
  )
  return (
    <a className="tracechip" href={url} target="_blank" rel="noopener noreferrer"
       title={title || "Open this step's trace in Langfuse (observability)"}>
      📊 {label}
    </a>
  )
}

// "By WCAG criterion" breakdown — aggregates the authoritative per-rule outcomes
// (PASS / FAIL / SKIP) the scanner recorded into scan_rule_traces, so users see exactly
// what each check did across the estate instead of only the summary tiles.
export function RuleBreakdown({ scanId }) {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!scanId) { setRows(null); return }
    let cancelled = false
    getScanTraces(scanId)
      .then((r) => { if (!cancelled) setRows(Array.isArray(r) ? r : []) })
      .catch(() => { if (!cancelled) setRows([]) })
    return () => { cancelled = true }
  }, [scanId])
  if (rows && rows.length === 0) return null      // discover-only scan — no per-rule data

  const byRule = {}
  ;(rows || []).forEach((r) => {
    const k = r.rule_id
    if (!byRule[k]) byRule[k] = { id: r.rule_id, name: r.plain_name || r.rule_name, level: r.level, pass: 0, fail: 0, skip: 0, findings: 0 }
    const o = String(r.outcome || '').toUpperCase()
    if (o === 'PASS') byRule[k].pass++
    else if (o === 'FAIL') byRule[k].fail++
    else byRule[k].skip++
    byRule[k].findings += r.finding_count || 0
  })
  const rules = Object.values(byRule).sort((a, b) => b.fail - a.fail || a.id.localeCompare(b.id))
  if (!rules.length) return null
  const shown = open ? rules : rules.slice(0, 6)
  const files = new Set((rows || []).map((r) => r.file)).size

  return (
    <section className="panel rulebreak">
      <div className="rubrichdr">
        <h2 style={{ margin: 0 }}>By WCAG criterion <span className="muted">· what each check found across {files.toLocaleString()} documents</span></h2>
        <span className="muted" style={{ fontSize: 12 }}>{rules.length} criteria evaluated</span>
      </div>
      <div className="rulerows">
        {shown.map((r) => {
          const total = r.pass + r.fail + r.skip || 1
          return (
            <div className="rulerow" key={r.id}>
              <div className="rulemeta"><b>{r.id}</b> <span className="lvlpill">{r.level}</span> <span>{r.name}</span></div>
              <div className="rulebar" title={`${r.pass} pass · ${r.fail} fail · ${r.skip} N/A`}>
                <i className="rb-pass" style={{ width: `${(r.pass / total) * 100}%` }} />
                <i className="rb-fail" style={{ width: `${(r.fail / total) * 100}%` }} />
                <i className="rb-skip" style={{ width: `${(r.skip / total) * 100}%` }} />
              </div>
              <div className="rulecounts">
                <span className="rc-pass">{r.pass.toLocaleString()} pass</span>
                {r.fail ? <span className="rc-fail">{r.fail.toLocaleString()} fail</span> : null}
                {r.skip ? <span className="rc-skip">{r.skip.toLocaleString()} N/A</span> : null}
              </div>
            </div>
          )
        })}
      </div>
      {rules.length > 6 && <button className="ghost small" style={{ marginTop: 10 }} onClick={() => setOpen(!open)}>{open ? 'Show less' : `Show all ${rules.length} criteria`}</button>}
    </section>
  )
}
