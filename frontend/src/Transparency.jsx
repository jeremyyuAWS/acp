import { useState, useEffect } from 'react'
import { openTraceUrl, getTraceStatus, getScanTraces } from './api.js'
import SegmentDrawer from './SegmentDrawer.jsx'
import FileDrawer from './FileDrawer.jsx'

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
export function TraceChip({ scanId, kind = 'session', file = null, label = 'View trace', title, refreshKey = 0 }) {
  const url = openTraceUrl(scanId, kind, file)
  const [available, setAvailable] = useState(null)
  useEffect(() => {
    if (!url) return
    let cancelled = false
    // refreshKey re-checks availability after an event that may have CREATED the
    // trace (e.g. remediate-now just wrote a Remediate span) — with retries to ride
    // out Langfuse's async ingestion, instead of the chip staying greyed until the
    // drawer is closed and reopened.
    const attempt = (retries) => getTraceStatus(scanId, kind, file)
      .then((r) => {
        if (cancelled) return
        if (r?.available) { setAvailable(true); return }
        if (retries > 0) setTimeout(() => { if (!cancelled) attempt(retries - 1) }, 2500)
        else setAvailable(false)
      })
      .catch(() => { if (!cancelled) setAvailable(false) })
    attempt(refreshKey > 0 ? 3 : 0)
    return () => { cancelled = true }
  }, [scanId, kind, file, url, refreshKey])

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

// WCAG failure heatmap: top failing rules × department, so a reviewer sees at a glance
// WHERE the biggest problems concentrate, not just which rules fail most overall.
// Color intensity = fail count (darker = worse), same orange family as rb-fail.
function FailureHeatmap({ rows, files, topRules, onCellClick }) {
  const fileByName = {}
  ;(files || []).forEach((f) => { fileByName[f.file] = f })
  const deptOf = {}
  ;(files || []).forEach((f) => { deptOf[f.file] = f.department || f.dept || 'Unassigned' })
  if (!Object.keys(deptOf).length) return null   // no department data available — skip silently

  const ruleIds = new Set(topRules.map((r) => r.id))
  const depts = new Set()
  const cell = {}       // `${ruleId}::${dept}` -> fail count
  const cellFiles = {}  // `${ruleId}::${dept}` -> failing file objects
  rows.forEach((r) => {
    if (!ruleIds.has(r.rule_id) || String(r.outcome || '').toUpperCase() !== 'FAIL') return
    const d = deptOf[r.file] || 'Unassigned'
    depts.add(d)
    const k = `${r.rule_id}::${d}`
    cell[k] = (cell[k] || 0) + 1
    ;(cellFiles[k] ||= []).push(fileByName[r.file] || { file: r.file, score: null })
  })
  if (!depts.size) return null
  const deptList = [...depts].sort()
  const max = Math.max(1, ...Object.values(cell))

  return (
    <div className="heatmap" role="table" aria-label="WCAG failures by rule and department">
      <div className="heatrow heathdr" role="row">
        <span className="heatlabel" role="columnheader">Rule</span>
        {deptList.map((d) => <span className="heatcol" role="columnheader" key={d}>{d}</span>)}
      </div>
      {topRules.map((r) => (
        <div className="heatrow" role="row" key={r.id}>
          <span className="heatlabel" role="rowheader" title={r.name}><b>{r.id}</b> {r.name}</span>
          {deptList.map((d) => {
            const k = `${r.id}::${d}`
            const n = cell[k] || 0
            const alpha = n ? 0.15 + 0.85 * (n / max) : 0
            return (
              <button type="button" className="heatcell" role="cell" key={d} disabled={!n}
                    style={{ background: n ? `rgba(201,116,43,${alpha.toFixed(2)})` : 'transparent',
                             cursor: n ? 'pointer' : 'default' }}
                    title={n ? `${r.id} × ${d}: ${n} failing document${n === 1 ? '' : 's'} — click to view` : `${r.id} × ${d}: no failures`}
                    onClick={() => n && onCellClick(r, d, cellFiles[k])}>
                {n || ''}
              </button>
            )
          })}
        </div>
      ))}
    </div>
  )
}

// "By WCAG criterion" breakdown — aggregates the authoritative per-rule outcomes
// (PASS / FAIL / SKIP) the scanner recorded into scan_rule_traces, so users see exactly
// what each check did across the estate instead of only the summary tiles.
export function RuleBreakdown({ scanId, files }) {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(false)
  const [seg, setSeg] = useState(null)
  const [sel, setSel] = useState(null)
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
  const fileCount = new Set((rows || []).map((r) => r.file)).size
  const failingRules = rules.filter((r) => r.fail > 0).slice(0, 8)

  return (
    <section className="panel rulebreak">
      <div className="rubrichdr">
        <h2 style={{ margin: 0 }}>By WCAG criterion <span className="muted">· what each check found across {fileCount.toLocaleString()} documents</span></h2>
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
      {failingRules.length > 0 && (
        <>
          <h3 className="heatmaptitle">Where failures concentrate <span className="muted">· top {failingRules.length} failing criteria by department</span></h3>
          <FailureHeatmap rows={rows || []} files={files} topRules={failingRules}
                           onCellClick={(rule, dept, cellFiles) => setSeg({
                             title: `${rule.id} · ${dept}`,
                             subtitle: `${cellFiles.length} document${cellFiles.length === 1 ? '' : 's'} failing "${rule.name}"`,
                             files: cellFiles,
                           })} />
        </>
      )}
      {seg && <SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={(f) => { setSeg(null); setSel(f) }} />}
      {sel && <FileDrawer file={sel} scanId={scanId} onClose={() => setSel(null)} />}
    </section>
  )
}
