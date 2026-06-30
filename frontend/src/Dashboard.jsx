import { useState } from 'react'
import { openReport } from './api'
import { ScoreRing, Sparkline } from './ScoreRing.jsx'
import { Donut, Bars, statusSegments, severityItems } from './charts.jsx'
import FileDrawer, { critLabel } from './FileDrawer.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import Tag from './Tag.jsx'
import Insight from './Insight.jsx'

const CRIT = {
  SC_1_1_1: '1.1.1 non-text', SC_1_3_1: '1.3.1 structure', SC_2_4_2: '2.4.2 page titled',
  SC_2_4_4: '2.4.4 link purpose', SC_3_1_1: '3.1.1 language',
}
const scoreColor = (s) => (s >= 90 ? '#639922' : s >= 50 ? '#BF8C00' : '#2E72C9')
const statusOf = (f) => (f.status === 'error' ? 'unanalysable' : f.status === 'uncertain' ? 'uncertain' : f.compliant ? 'certifiable' : 'issues')
const BADGE = {
  certifiable: ['#E7F0DC', '#3B6D11'], issues: ['#FAEEDA', '#854F0B'],
  uncertain: ['#E6EFFB', '#2A5E9E'], unanalysable: ['#EEEDEA', '#5F5E5A'],
}

// Google Drive appends " (1)", " (2)"… when the same file is uploaded more than
// once. Strip the suffix to recover the logical document name.
const baseName = (name) => name.replace(/ \(\d+\)(\.[^.]+)$/, '$1')

// Collapse duplicate uploads into one representative row per logical document,
// carrying a copy count + the list of actual file names.
function groupDuplicates(files) {
  const map = new Map()
  for (const f of files) {
    const k = baseName(f.file)
    const g = map.get(k)
    if (!g) { map.set(k, { rep: f, copies: 1, names: [f.file] }) }
    else { g.copies += 1; g.names.push(f.file); if (f.file === k) g.rep = f }
  }
  return [...map.values()].map((g) => ({ ...g.rep, _copies: g.copies, _names: g.names }))
}

export default function Dashboard({ run, files, trend, delta, deltaKey, scanList = [], onPickScan }) {
  const [sel, setSel] = useState(null)
  const [seg, setSeg] = useState(null)
  const [groupDupes, setGroupDupes] = useState(true)
  const rows = groupDupes ? groupDuplicates(files) : files
  const dupeCount = files.length - groupDuplicates(files).length

  // ── File-inventory navigation: search + status/type filters + sort + paged render ──
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [sortBy, setSortBy] = useState('file')
  const [sortDir, setSortDir] = useState('asc')
  const [limit, setLimit] = useState(1000)         // render budget — most narrowed views fit; "show more" beyond
  const extOf = (f) => (f.file.includes('.') ? f.file.split('.').pop().toLowerCase() : '')
  const statusCounts = rows.reduce((a, f) => { const s = statusOf(f); a[s] = (a[s] || 0) + 1; return a }, {})
  const typeList = [...new Set(rows.map(extOf))].filter(Boolean).sort()
  const q = query.trim().toLowerCase()
  const reset = () => setLimit(1000)               // a new query/filter starts from the top
  const filtered = rows.filter((f) =>
    (!q || (groupDupes && f._copies > 1 ? baseName(f.file) : f.file).toLowerCase().includes(q)) &&
    (statusFilter === 'all' || statusOf(f) === statusFilter) &&
    (typeFilter === 'all' || extOf(f) === typeFilter))
  const sorted = [...filtered].sort((a, b) => {
    let r = 0
    if (sortBy === 'file') r = a.file.localeCompare(b.file)
    else if (sortBy === 'score') r = (a.score ?? -1) - (b.score ?? -1)
    else if (sortBy === 'findings') r = (a.issues?.length || 0) - (b.issues?.length || 0)
    else if (sortBy === 'status') r = statusOf(a).localeCompare(statusOf(b))
    return sortDir === 'asc' ? r : -r
  })
  const shown = sorted.slice(0, limit)
  const sortClick = (col) => { if (sortBy === col) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc')); else { setSortBy(col); setSortDir(col === 'file' ? 'asc' : 'desc') } }
  const arrow = (col) => (sortBy === col ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')
  const pickStatus = (s) => { const fs = files.filter((f) => statusOf(f) === s.label); setSeg({ title: `${s.label} documents`, subtitle: `${fs.length} of ${files.length}`, files: fs }) }
  const pickSeverity = (it) => { const sev = it.label.toUpperCase(); const fs = files.filter((f) => (f.issues || []).some((i) => i.severity === sev)); setSeg({ title: `${it.label} findings`, subtitle: `${fs.length} document(s) affected`, files: fs }) }
  const pickCrit = (c) => { const fs = files.filter((f) => (f.issues || []).some((i) => i.wcag === c)); setSeg({ title: `${critLabel(c)}`, subtitle: `${fs.length} document(s) failing this criterion`, files: fs }) }
  const critFails = {}
  files.forEach((f) => new Set(f.issues.map((i) => i.wcag)).forEach((c) => { critFails[c] = (critFails[c] || 0) + 1 }))
  const maxFail = Math.max(1, ...Object.values(critFails))

  const pctOf = (a, b) => (b ? Math.round((a / b) * 100) : 0)
  const sevList = severityItems(files)
  const sevTotal = sevList.reduce((a, s) => a + s.value, 0)
  const sevHigh = sevList.filter((s) => s.label === 'critical' || s.label === 'serious').reduce((a, s) => a + s.value, 0)
  const topCrit = Object.entries(critFails).sort((a, b) => b[1] - a[1])[0]
  const INS = {
    status: `${pctOf(run.certifiable, run.files)}% of documents are certifiable. The ${run.uncertain} 'uncertain' docs had a rule that couldn't be evaluated — re-scanning with full access usually clears most; the rest are largely auto-fixable.`,
    severity: sevTotal ? `Critical & serious make up ${pctOf(sevHigh, sevTotal)}% of findings — ${pctOf(sevHigh, sevTotal) > 40 ? 'above' : 'near'} the ~40% norm. Front-load alt-text and tagging fixes for the biggest risk reduction.` : 'No open findings.',
    wcag: topCrit ? `${CRIT[topCrit[0]] ?? topCrit[0]} fails in the most files (${topCrit[1]}). It's a single, largely automatable fix class — a strong first remediation target.` : '',
  }

  // Master score = the latest run; the scan history below tracks it over time.
  const isLatest = !scanList.length || scanList[0]?.id === run.id
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—')

  return (
    <>
      <div className="dashtoolbar">
        <button className="exportbtn" onClick={() => openReport(run.id)}>⤓ Export PDF report</button>
      </div>
      <section className="hero">
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, color: '#6B7280', textTransform: 'uppercase', marginBottom: 6 }}>Master score</div>
          <ScoreRing score={run.avg_score} delta={delta} deltaKey={deltaKey} />
          <div className="muted" style={{ fontSize: 11, marginTop: 6, whiteSpace: 'nowrap' }}>
            {isLatest ? '★ latest scan' : 'selected scan'}{run.completed_at ? ` · ${fmtDate(run.completed_at)}` : ''}
          </div>
        </div>
        <div className="heroright">
          <div className="herostats">
            <div className="herostat"><b style={{ color: '#3B6D11' }}>{run.certifiable}</b><span>certifiable</span></div>
            <div className="herostat"><b style={{ color: '#854F0B' }}>{run.uncertain}</b><span>uncertain</span></div>
            <div className="herostat"><b style={{ color: '#1F5FA8' }}>{run.error}</b><span>unanalysable</span></div>
            <div className="herostat"><b>{run.files}</b><span>files</span></div>
          </div>
          {trend.length > 1 && new Set(trend).size > 1 && (
            <div className="herotrend">
              <span className="muted">compliance trend · {trend.length} scans</span>
              <Sparkline points={trend} />
            </div>
          )}
        </div>
      </section>
      {scanList.length > 0 && (
        <section className="panel">
          <h2>Scan history <span className="muted" style={{ fontWeight: 400 }}>· master score = latest run · click a row to view it</span></h2>
          <div className="tablewrap"><table>
            <thead><tr><th></th><th>scan</th><th>score</th><th>change</th><th>certifiable</th><th>source</th></tr></thead>
            <tbody>
              {scanList.map((s, i) => {
                const prev = scanList[i + 1]
                const d = (prev?.avg_score != null && s.avg_score != null) ? s.avg_score - prev.avg_score : null
                const isCurrent = s.id === run.id
                return (
                  <tr key={s.id} className="filerow" role="button" tabIndex={0}
                    onClick={() => onPickScan?.(s.id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPickScan?.(s.id) } }}
                    style={isCurrent ? { background: '#F4EEFC' } : undefined}>
                    <td>{i === 0 && <span className="badge" style={{ background: '#EDE7FB', color: '#6D28D9' }}>★ master</span>}</td>
                    <td>{fmtDate(s.completed_at)}{isCurrent && <span className="muted"> · viewing</span>}</td>
                    <td className="scorecell"><b>{s.avg_score ?? 'n/a'}</b><span className="muted">/100</span></td>
                    <td>{d == null ? <span className="muted">—</span> : (
                      <span style={{ color: d > 0 ? '#3B6D11' : d < 0 ? '#B43A2A' : '#6B7280', fontWeight: 600, fontSize: 12 }}>
                        {d > 0 ? `▲ +${d}` : d < 0 ? `▼ ${d}` : '±0'}</span>)}</td>
                    <td className="muted">{s.certifiable ?? '—'} / {(s.files ?? 0).toLocaleString()}</td>
                    <td className="muted">{s.source}</td>
                  </tr>
                )
              })}
            </tbody>
          </table></div>
        </section>
      )}
      <div className="chartrow">
        <section className="panel"><h2>Compliance status <span className="muted" style={{ fontWeight: 400 }}>· click to drill in</span></h2><Donut segments={statusSegments(run)} caption="documents" onPick={pickStatus} /><Insight text={INS.status} /></section>
        <section className="panel"><h2>Findings by severity <span className="muted" style={{ fontWeight: 400 }}>· click to drill in</span></h2>
          {severityItems(files).length ? <Bars items={severityItems(files)} onPick={pickSeverity} /> : <p className="muted">No open findings.</p>}
          <Insight text={INS.severity} />
        </section>
      </div>
      {Object.keys(critFails).length > 0 && (
        <section className="panel">
          <h2>WCAG 2.1 criteria failing, by file count <span className="muted" style={{ fontWeight: 400 }}>· click to drill in</span></h2>
          {Object.entries(critFails).sort((a, b) => b[1] - a[1]).map(([c, n]) => (
            <button className="critrow pickrow" key={c} style={{ width: '100%' }} onClick={() => pickCrit(c)}>
              <span className="critlabel" style={{ textAlign: 'left' }}>{CRIT[c] ?? critLabel(c)}</span>
              <span className="track"><i style={{ width: `${(n / maxFail) * 100}%`, background: n >= maxFail ? '#2E72C9' : '#BF8C00' }} /></span>
              <span className="critn">{n}</span>
            </button>
          ))}
          <Insight text={INS.wcag} />
        </section>
      )}
      <section className="panel">
        <h2 style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span>File inventory · <span style={{ fontWeight: 400 }}>
            {sorted.length === rows.length ? `${rows.length.toLocaleString()} document${rows.length === 1 ? '' : 's'}` : `${sorted.length.toLocaleString()} of ${rows.length.toLocaleString()}`} · click a row for details</span></span>
          {dupeCount > 0 && (
            <label className="muted" style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 400, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={groupDupes} onChange={(e) => setGroupDupes(e.target.checked)} />
              Group duplicate uploads <span style={{ opacity: 0.7 }}>({dupeCount} copies)</span>
            </label>
          )}
        </h2>
        {/* Navigation toolbar: search · status chips · type filter */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', margin: '2px 0 12px' }}>
          <input value={query} onChange={(e) => { setQuery(e.target.value); reset() }} placeholder="🔍 Search files…"
            aria-label="Search files by name"
            style={{ flex: '1 1 200px', minWidth: 180, padding: '7px 11px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)', color: 'inherit', fontSize: 13 }} />
          {['all', 'certifiable', 'issues', 'uncertain', 'unanalysable'].filter((s) => s === 'all' || statusCounts[s]).map((s) => (
            <button key={s} type="button" onClick={() => { setStatusFilter(s); reset() }}
              className={statusFilter === s ? 'fchip on' : 'fchip'} style={{ fontSize: 12, textTransform: 'capitalize' }}>
              {s === 'all' ? 'All' : s}{s !== 'all' && <span style={{ opacity: 0.65, marginLeft: 5 }}>{statusCounts[s]}</span>}
            </button>
          ))}
          {typeList.length > 1 && (
            <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); reset() }} aria-label="Filter by file type"
              style={{ fontSize: 12, padding: '6px 9px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)', color: 'inherit', cursor: 'pointer' }}>
              <option value="all">All types</option>
              {typeList.map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
            </select>
          )}
        </div>
        <div className="tablewrap"><table>
          <thead><tr>
            {[['file', 'file'], ['status', 'status'], ['score', 'score'], ['findings', 'findings']].map(([col, label]) => (
              <th key={col} onClick={() => sortClick(col)} style={{ cursor: 'pointer', userSelect: 'none' }}
                  title="Click to sort">{label}<span style={{ color: '#6D28D9' }}>{arrow(col)}</span></th>
            ))}
          </tr></thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={4} className="muted" style={{ textAlign: 'center', padding: '24px' }}>No files match your search or filters.</td></tr>
            )}
            {shown.map((f) => {
              const st = statusOf(f); const [bg, fg] = BADGE[st]
              return (
                <tr key={f.file} className="filerow" role="button" tabIndex={0}
                  onClick={() => setSel(f)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(f) } }}>
                  <td className="fname">{groupDupes && f._copies > 1 ? baseName(f.file) : f.file}
                    {groupDupes && f._copies > 1 && (
                      <span title={`${f._copies} identical copies in Drive:\n${f._names.join('\n')}`}
                        style={{ marginLeft: 8, fontSize: 11, fontWeight: 600, color: '#854F0B',
                          background: '#FAEEDA', borderRadius: 10, padding: '1px 7px', verticalAlign: 'middle' }}>
                        ×{f._copies} copies
                      </span>
                    )}
                    <div className="filemeta">
                      {f.sourceName && <span className="srcpill">{f.sourceName}</span>}
                      {(f.tags || []).slice(0, 4).map((t) => <Tag key={t} t={t} />)}
                    </div>
                  </td>
                  <td><span className="badge" style={{ background: bg, color: fg }}>{st}</span></td>
                  <td>{f.score === null ? <span className="muted">n/a</span> : (
                    <span className="scorecell"><span>{st === 'uncertain' ? '≤' : ''}{f.score}</span>
                      <span className="track sm"><i style={{ width: `${f.score}%`, background: scoreColor(f.score) }} /></span></span>)}</td>
                  <td className="muted">{st === 'uncertain' ? `${f.skipped_rules} rule(s) skipped`
                    : f.issues.length ? `${f.issues.length} issue(s)` : (f.status === 'error' ? 'could not analyse' : 'clean')}</td>
                </tr>
              )
            })}
          </tbody>
        </table></div>
        {sorted.length > limit && (
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <button className="ghost" onClick={() => setLimit((n) => n + 1000)}>
              Show 1,000 more <span className="muted">· {(sorted.length - limit).toLocaleString()} remaining</span>
            </button>
          </div>
        )}
      </section>
      {seg && <SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={(f) => { setSeg(null); setSel(f) }} />}
      {sel && <FileDrawer file={sel} onClose={() => setSel(null)} />}
    </>
  )
}
