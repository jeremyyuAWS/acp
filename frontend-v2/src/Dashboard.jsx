import { useState, useEffect } from 'react'
import { openReport, getScanDiff } from './api'
import { ScoreRing } from './ScoreRing.jsx'
import FileDrawer from './FileDrawer.jsx'
import Tag from './Tag.jsx'
import { baseName, groupDuplicates, duplicateFiles } from './dedupe.js'
import { statusOf, statusCounts as countStatuses, ALL_STATUSES, STATUS_BADGE, STATUS_TAG_LABEL, NOT_ASSESSED } from './docStatus.js'

const scoreColor = (s) => (s >= 90 ? '#639922' : s >= 50 ? '#BF8C00' : '#2E72C9')
// The verdict AND its palette now come from docStatus.js. This module kept a verbatim copy of
// the badge map, which is a slower version of the same failure the copied statusOf caused: a
// verdict added to the shared derivation renders here with `BADGE[st]` undefined, so the row
// throws instead of showing the new state. One map, one place to add a colour.

export default function Dashboard({ run, files, trend, delta, deltaKey, scanList = [], onPickScan }) {
  const [sel, setSel] = useState(null)
  const [groupDupes, setGroupDupes] = useState(true)
  const rows = groupDupes ? groupDuplicates(files) : files
  const dupeCount = files.length - groupDuplicates(files).length
  // COUNT THE DOCUMENTS, DON'T SUBTRACT THEM — the same fix #77 made to charts.jsx's donut,
  // which this hero did not get. "issues" was `run.files - run.certifiable - run.uncertain -
  // run.error`, and the claim that made it look safe ("the four numbers sum to run.files by
  // construction") is what made it wrong: statusOf() has FIVE verdicts, so every 'clean' and
  // every unscored document landed in "issues" by elimination. Seen live on 2026-07-30 —
  // "0 certifiable · 2 issues · 0 uncertain · 0 unanalysable · 2 files" above two rows that
  // both read "clean", on a scan where nothing had been scored at all. Not one of those 2
  // issues came from a finding.
  //
  // Counting over `files` (the RAW, un-grouped prop — `rows` above is the de-duplicated view)
  // keeps the sum-to-total property the subtraction was there for, and now it is an identity
  // that holds because every bucket is counted rather than one being a remainder.
  const heroCounts = countStatuses(files)
  const heroTotal = files.length

  // ── Net-new / changed only ── reuses the ADR 0009 scan-diff (already computed for
  // Regression Radar) so re-scanning a stable estate doesn't dump the FULL inventory
  // back in your face every time — by default, only show what's actually new or whose
  // score changed since the immediately-prior scan. undefined = not checked yet,
  // null = no usable prior scan to diff against (first scan ever, or fetch failed) —
  // in both those cases the filter never applies, so this can't hide everything.
  const curIdx = scanList.findIndex((s) => s.id === run.id)
  const prevId = curIdx > -1 ? scanList[curIdx + 1]?.id : undefined
  const [diff, setDiff] = useState(undefined)
  const [onlyChanged, setOnlyChanged] = useState(true)
  useEffect(() => {
    setDiff(undefined)
    if (!prevId) { setDiff(null); return undefined }
    let alive = true
    getScanDiff(run.id, prevId).then((d) => { if (alive) setDiff(d || null) }).catch(() => { if (alive) setDiff(null) })
    return () => { alive = false }
  }, [run.id, prevId])
  const changedNames = diff ? new Set([
    ...(diff.new || []).map((f) => f.file),
    ...(diff.regressed || []).map((f) => f.file),
    ...(diff.improved || []).map((f) => f.file),
  ]) : null
  const namesOf = (f) => f._names || [f.file]
  const unchangedCount = changedNames ? rows.filter((f) => !namesOf(f).some((n) => changedNames.has(n))).length : 0
  // "Previously scanned" = present in the prior scan too (i.e. NOT new this time) — the
  // complement of diff.new, regardless of whether its score changed.
  const newNamesOnly = diff ? new Set((diff.new || []).map((f) => f.file)) : null
  const prevScannedCount = diff ? rows.filter((f) => !namesOf(f).some((n) => newNamesOnly.has(n))).length : 0
  // Duplicate-name files — same set the Classify panel (Discover.jsx) drills into.
  const duplicateNameSet = new Set(duplicateFiles(files).map((f) => f.file))
  const dupesOnlyCount = rows.filter((f) => namesOf(f).some((n) => duplicateNameSet.has(n))).length

  // ── File-inventory navigation: search + status/type filters + sort + paged render ──
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [dupesOnlyFilter, setDupesOnlyFilter] = useState(false)
  const [prevScannedOnlyFilter, setPrevScannedOnlyFilter] = useState(false)
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
    (typeFilter === 'all' || extOf(f) === typeFilter) &&
    (!onlyChanged || !changedNames || namesOf(f).some((n) => changedNames.has(n))) &&
    (!dupesOnlyFilter || namesOf(f).some((n) => duplicateNameSet.has(n))) &&
    (!prevScannedOnlyFilter || !diff || !namesOf(f).some((n) => newNamesOnly.has(n))))
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
          <div className="score-benchmark">
            <span>WCAG AA target: <b>90+</b></span>
            <span>industry avg: <b>~72</b></span>
            {run.avg_score != null && run.avg_score >= 90
              ? <span style={{ color: '#3B6D11', fontWeight: 600 }}>✓ above target</span>
              : run.avg_score != null && run.avg_score >= 80
                ? <span style={{ color: '#854F0B' }}>approaching target</span>
                : run.avg_score != null
                  ? <span style={{ color: '#7B1D1D' }}>below target</span>
                  : null}
          </div>
        </div>
        <div className="heroright">
          {/* Every verdict statusOf() can return gets a tile — the whole partition, so no
              document can be absorbed into a bucket it doesn't belong in. A tile with a zero
              stays visible: "0 not assessed" is a fact a reviewer wants confirmed, and hiding
              the bucket is what let the estate look fully measured. Colours are the File
              Inventory's own status badges (STATUS_BADGE), and "= files" is marked visually as
              the SUM, not an independent count. */}
          <div className="herostats">
            {[['certifiable', 'certifiable'], ['issues', 'issues'], ['clean', 'no findings'],
              [NOT_ASSESSED, 'not assessed'], ['uncertain', 'uncertain'], ['unanalysable', 'unanalysable']]
              .map(([key, label]) => (
                <div className="herostat" key={key}>
                  <b style={{ color: STATUS_BADGE[key][1] }}>{heroCounts[key]}</b><span>{label}</span>
                </div>
              ))}
            <div className="herostat" style={{ borderLeft: '1px dashed var(--line)', paddingLeft: 14, marginLeft: 4 }} title="The sum of the six categories to the left">
              <b>= {heroTotal}</b><span>files</span>
            </div>
          </div>
        </div>
      </section>
      <section className="panel">
        <h2 style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span>File inventory · <span style={{ fontWeight: 400 }}>
            {sorted.length === rows.length ? `${rows.length.toLocaleString()} document${rows.length === 1 ? '' : 's'}` : `${sorted.length.toLocaleString()} of ${rows.length.toLocaleString()}`} · click a row for details</span></span>
          {(changedNames || dupeCount > 0) && (
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
              {changedNames && (
                <label className="muted" style={{ fontSize: 12, fontWeight: 400, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
                       title={`Compares this scan against the immediately-prior one — only documents that are new or whose score changed are shown by default. ${unchangedCount} unchanged document${unchangedCount !== 1 ? 's are' : ' is'} hidden.`}>
                  <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
                  Only new/changed <span>({unchangedCount} unchanged hidden)</span>
                </label>
              )}
              {diff && (
                <label className="muted" style={{ fontSize: 12, fontWeight: 400, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
                       title="Filter to files that already appeared in the prior scan (i.e. NOT new this time) — useful for auditing what's being carried forward rather than freshly discovered.">
                  <input type="checkbox" checked={prevScannedOnlyFilter} onChange={(e) => setPrevScannedOnlyFilter(e.target.checked)} />
                  Previously scanned only <span>({prevScannedCount})</span>
                </label>
              )}
              {dupeCount > 0 && (
                <label className="muted" style={{ fontSize: 12, fontWeight: 400, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input type="checkbox" checked={groupDupes} onChange={(e) => setGroupDupes(e.target.checked)} />
                  Group duplicate uploads <span>({dupeCount} copies)</span>
                </label>
              )}
              {dupesOnlyCount > 0 && (
                <label className="muted" style={{ fontSize: 12, fontWeight: 400, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
                       title="Filter to ONLY files that share a name with another file — the set worth reviewing for accidental duplicate uploads.">
                  <input type="checkbox" checked={dupesOnlyFilter} onChange={(e) => setDupesOnlyFilter(e.target.checked)} />
                  Duplicates only <span>({dupesOnlyCount})</span>
                </label>
              )}
            </div>
          )}
        </h2>
        {/* Navigation toolbar: search · status chips · type filter */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', margin: '2px 0 12px' }}>
          <input value={query} onChange={(e) => { setQuery(e.target.value); reset() }} placeholder="🔍 Search files…"
            aria-label="Search files by name"
            style={{ flex: '1 1 200px', minWidth: 180, padding: '7px 11px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)', color: 'inherit', fontSize: 13 }} />
          {/* Driven by ALL_STATUSES, not a hand-written subset: 'clean' had no chip and the
              unscored documents had no chip either, so the two verdicts a reviewer most needs
              to isolate were the two you could not filter to. A chip still only appears when
              some document is actually in that bucket. */}
          {['all', ...ALL_STATUSES].filter((s) => s === 'all' || statusCounts[s]).map((s) => (
            <button key={s} type="button" onClick={() => { setStatusFilter(s); reset() }}
              className={statusFilter === s ? 'fchip on' : 'fchip'} style={{ fontSize: 12, textTransform: 'capitalize' }}>
              {s === 'all' ? 'All' : (STATUS_TAG_LABEL[s] || s)}{s !== 'all' && <span style={{ marginLeft: 5 }}>{statusCounts[s]}</span>}
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
              <tr><td colSpan={4} className="muted" style={{ textAlign: 'center', padding: '24px' }}>
                {onlyChanged && changedNames && !q && statusFilter === 'all' && typeFilter === 'all'
                  ? <>✓ Nothing new or changed since the last scan — all {rows.length.toLocaleString()} documents are stable. <button className="ghost small" onClick={() => setOnlyChanged(false)}>Show all</button></>
                  : 'No files match your search or filters.'}
              </td></tr>
            )}
            {shown.map((f) => {
              const st = statusOf(f); const [bg, fg] = STATUS_BADGE[st]
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
                  <td><span className="badge" style={{ background: bg, color: fg }}
                    title={st === NOT_ASSESSED ? 'Listed from the source, but never opened or scored — nothing is known about this document’s findings yet' : undefined}>
                    {STATUS_TAG_LABEL[st] || st}</span></td>
                  {/* `== null`, not `=== null`: a record with score absent rather than
                      explicitly null is just as unscored, and rendered `undefined%` here. */}
                  <td>{f.score == null ? <span className="muted">n/a</span> : (
                    <span className="scorecell"><span>{st === 'uncertain' ? '≤' : ''}{f.score}</span>
                      <span className="track sm"><i style={{ width: `${f.score}%`, background: scoreColor(f.score) }} /></span></span>)}</td>
                  {/* "clean" was the fall-through for this cell too, so a document nobody
                      opened reported "clean" findings beside its "n/a" score. An unmeasured
                      document has no findings COUNT — that is not the same as having none. */}
                  <td className="muted">{st === 'uncertain' ? `${f.skipped_rules} rule(s) skipped`
                    : (f.issues || []).length ? `${f.issues.length} issue(s)`
                    : st === 'unanalysable' ? 'could not analyse'
                    : st === NOT_ASSESSED ? 'not assessed' : 'clean'}</td>
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
      {sel && <FileDrawer file={sel} scanId={run.id} onClose={() => setSel(null)} />}
    </>
  )
}
