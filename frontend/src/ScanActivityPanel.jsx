import { useEffect, useMemo, useState } from 'react'
import { getSessionTraceData } from './api.js'
import TracePanel from './TracePanel.jsx'

const stamp = (value) => {
  if (!value) return 'Unknown time'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function Funnel({ files }) {
  const discovered = files.length
  const assessed = files.filter((f) => !!f.result).length
  const remediated = files.filter((f) => f.result?.remediation?.remediated).length
  const stages = [
    ['Discovered', discovered, '#54404F'],
    ['Assessed', assessed, '#2864B0'],
    ['Remediated', remediated, '#287D4A'],
  ]
  return <div aria-label="Scan lifecycle progress" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(140px, 1fr))', gap: 10, marginTop: 14 }}>
    {stages.map(([label, value, color]) => <div key={label} style={{ padding: '11px 13px', border: '1px solid var(--line)', borderRadius: 9 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: 12 }}><b>{label}</b><b>{value.toLocaleString()}</b></div>
      <div style={{ height: 6, borderRadius: 10, background: '#E9E5EA', marginTop: 8, overflow: 'hidden' }}><div style={{ width: `${discovered ? value / discovered * 100 : 0}%`, height: '100%', background: color }} /></div>
      <div className="muted" style={{ fontSize: 11, marginTop: 5 }}>{discovered ? Math.round(value / discovered * 100) : 0}% of discovered</div>
    </div>)}
  </div>
}

const stageMark = (done, label) => <span aria-label={`${label}: ${done ? 'complete' : 'not recorded'}`} title={`${label}: ${done ? 'complete' : 'not recorded'}`} style={{ color: done ? '#287D4A' : 'var(--muted)', fontWeight: 700 }}>{done ? '✓' : '—'}</span>

export default function ScanActivityPanel({ run, scanList = [] }) {
  const scans = useMemo(() => {
    const all = [...scanList]
    if (run?.id && !all.some((s) => s.id === run.id)) all.unshift(run)
    return all.filter((s) => s?.id).sort((a, b) => String(b.completed_at || b.created_at || '').localeCompare(String(a.completed_at || a.created_at || '')))
  }, [run, scanList])
  const [scanId, setScanId] = useState(run?.id || scans[0]?.id || '')
  const [state, setState] = useState({ loading: false, status: 'idle' })
  const [query, setQuery] = useState('')
  const [openFile, setOpenFile] = useState(null)
  const [expanded, setExpanded] = useState(true)

  useEffect(() => { if (run?.id) setScanId(run.id) }, [run?.id])
  const load = () => {
    if (!scanId) return
    let live = true
    setState({ loading: true, status: 'loading' })
    getSessionTraceData(scanId).then((r) => { if (live) setState({ loading: false, ...r }) })
      .catch(() => { if (live) setState({ loading: false, status: 'pending' }) })
    return () => { live = false }
  }
  useEffect(() => { if (expanded) return load() }, [scanId, expanded]) // eslint-disable-line react-hooks/exhaustive-deps

  const files = state.session?.files || []
  const visible = files.filter((f) => (f.document || '').toLowerCase().includes(query.trim().toLowerCase()))
  const selected = scans.find((s) => s.id === scanId)

  return <section className="panel" aria-labelledby="scan-activity-title" style={{ marginBottom: 14 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
      <div><h2 id="scan-activity-title" style={{ margin: 0 }}>Scan activity <span style={{ fontSize: 9.5, fontWeight: 700, color: '#287D4A', background: '#E8F5EC', border: '1px solid #B9DCC4', borderRadius: 4, padding: '1px 5px', verticalAlign: 'middle' }}>LIVE</span></h2><p className="muted" style={{ margin: '4px 0 0', fontSize: 12.5 }}>Discovery, assessment, and remediation activity from Langfuse—down to each file.</p></div>
      <button className="ghost small" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>{expanded ? 'Hide activity' : 'Show activity'}</button>
    </div>
    {expanded && <>
      <div style={{ display: 'flex', gap: 10, alignItems: 'end', flexWrap: 'wrap', marginTop: 14 }}>
        <label style={{ display: 'grid', gap: 4, fontSize: 12, fontWeight: 700 }}>Scan<select aria-label="Scan to inspect" value={scanId} onChange={(e) => { setScanId(e.target.value); setQuery('') }} style={{ minWidth: 240 }}>
          {scans.map((s) => <option key={s.id} value={s.id}>{stamp(s.completed_at || s.created_at)}{s.id === run?.id ? ' · current' : ''}</option>)}
        </select></label>
        {selected && <span className="muted" style={{ fontSize: 12, paddingBottom: 6 }}>{selected.source || selected.scope?.source || 'source'} · {selected.id.slice(0, 10)}</span>}
      </div>
      <div role="status" aria-live="polite">
        {state.loading && <p className="muted">Loading activity…</p>}
        {!state.loading && state.status === 'not_configured' && <p className="muted">Activity tracing is not configured for this deployment.</p>}
        {!state.loading && state.status === 'pending' && <p className="muted">Activity is still being recorded. <button className="ghost small" onClick={load}>Refresh</button></p>}
      </div>
      {!state.loading && state.status === 'ok' && state.session && <>
        <Funnel files={files} />
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginTop: 15 }}><b style={{ fontSize: 13 }}>File activity</b><input type="search" aria-label="Search file activity" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search files" style={{ width: 220 }} /></div>
        <div style={{ marginTop: 8, border: '1px solid var(--line)', borderRadius: 9, overflow: 'hidden' }}>
          <div aria-hidden="true" style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) 80px 80px 90px 100px', gap: 8, padding: '8px 12px', background: '#F5F3F6', fontSize: 11, fontWeight: 700 }}><span>File</span><span>Discover</span><span>Assess</span><span>Remediate</span><span /></div>
          {visible.length ? visible.slice(0, 100).map((f) => {
            const assessed = !!f.result, remediated = !!f.result?.remediation?.remediated
            return <div key={f.trace_id} style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) 80px 80px 90px 100px', gap: 8, alignItems: 'center', padding: '9px 12px', borderTop: '1px solid var(--line)', fontSize: 12 }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.document || f.trace_id}</span><span>{stageMark(true, 'Discover')}</span><span>{stageMark(assessed, 'Assess')}</span><span>{stageMark(remediated, 'Remediate')}</span><button className="ghost small" onClick={() => setOpenFile(f.document)}>View timeline</button>
            </div>
          }) : <p className="muted" style={{ padding: 12, margin: 0 }}>No matching file activity.</p>}
        </div>
        {state.session.truncated && <p className="muted" style={{ fontSize: 11 }}>Showing the first {files.length} of {state.session.total} files reported by Langfuse.</p>}
      </>}
    </>}
    {openFile && <TracePanel scanId={scanId} file={openFile} onClose={() => setOpenFile(null)} />}
  </section>
}
