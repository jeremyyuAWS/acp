import { useState } from 'react'
import { openReport } from './api'
import { ScoreRing } from './ScoreRing.jsx'
import FileDrawer from './FileDrawer.jsx'
import Tag from './Tag.jsx'

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
  // Master score = the latest run; the file inventory below is this assessment's per-document result.
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
        </div>
      </section>
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
      {sel && <FileDrawer file={sel} onClose={() => setSel(null)} />}
    </>
  )
}
