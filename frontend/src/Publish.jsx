import { useState } from 'react'
import FileDrawer from './FileDrawer.jsx'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import { openReport } from './api.js'
import { IDENTITY } from './sim.js'

const scoreColor = (s) => (s >= 80 ? '#3B6D11' : s >= 50 ? '#854F0B' : '#7B1D1D')

// Step 9 · Publish / Replace / Archive. Re-validated documents are published back
// to their source — replaced in place, the prior version archived, metadata
// updated, and owners notified. Simulated actions on the live certifiable set.
// readOnly: time-travel replay — publishing must act on the live estate, not a snapshot.
export default function Publish({ run, files = [], certified = [], readOnly = false, onPublish }) {
  const ready = files.filter((f) => f.compliant)
  const sfP = useSearchFilter('publish')
  const PUB_FACETS = [
    { key: 'type', label: 'Type', get: (f) => (f.file.split('.').pop() || '').toUpperCase() },
    { key: 'department', label: 'Dept', get: (f) => f.department },
    { key: 'source', label: 'Source', get: (f) => f.sourceName },
  ]
  const shownReady = sfP.active ? ready.filter(matchesFilters(sfP, PUB_FACETS, (f) => f.file)) : ready
  const [done, setDone] = useState({})
  const [sel, setSel] = useState(null)
  const publish = (file) => { setDone((d) => (d[file] ? d : { ...d, [file]: true })); onPublish?.(file) }
  const publishAll = () => { setDone(() => Object.fromEntries(ready.map((f) => [f.file, true]))); ready.forEach((f) => onPublish?.(f.file)) }
  const publishedCount = Object.keys(done).length + certified.length
  const pubStarted = Object.keys(done).length > 0   // zero the outcome cards until the user publishes
  const pct = run?.files ? Math.round((run.certifiable / run.files) * 100) : 0
  const onTrack = pct >= 80 || (run?.avg_score ?? 0) >= 80
  const reportDate = new Date(run?.completed_at || Date.now()).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  // Real publish history: files carry their own published_at once the scan is re-fetched
  // (persisted server-side by POST /scans/{sid}/publish) -- this replaces a client-derived
  // list that showed the SAME date for every entry and reset on reload. Falls back to
  // "just now" for a file published THIS session, before the next refetch catches up.
  const publishedAtByFile = {}
  files.forEach((f) => { if (f.published_at) publishedAtByFile[f.file] = f.published_at })
  const publishedEntries = [
    ...Object.keys(done).map((file) => ({ file, publishedAt: publishedAtByFile[file] || null })),
    ...certified.filter((c) => !done[c.file]).map((c) => ({ file: c.file, publishedAt: null, external: true })),
  ].sort((a, b) => (b.publishedAt || '').localeCompare(a.publishedAt || ''))
  const fmtPublished = (e) => e.publishedAt
    ? new Date(e.publishedAt).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : e.external ? 'via Upload' : 'just now'
  const publishedList = publishedEntries.map((e) => e.file)

  return (
    <>
      {/* The deliverable: a conformance-report header a compliance officer hands to legal. */}
      <section className="panel" style={{ borderLeft: '4px solid #3B6D11' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 18, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 340px' }}>
            <h2 style={{ margin: 0 }}>📜 Conformance Report</h2>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              {IDENTITY.org} · WCAG 2.1 Level AA · generated {reportDate}
            </div>
            <p style={{ fontSize: 13.5, lineHeight: 1.6, margin: '12px 0 0', maxWidth: 620 }}>
              This document estate was assessed against <b>WCAG 2.1 Level AA</b> — the ADA Title II, EAA, and Section 508 legal target.
              <b style={{ color: '#3B6D11' }}> {run?.certifiable ?? 0}</b> of <b>{(run?.files ?? 0).toLocaleString()}</b> documents are certifiable as conformant today ({pct}%){run?.error ? <> · {run.error} could not be analysed</> : null}.
            </p>
          </div>
          <div style={{ textAlign: 'center', minWidth: 124 }}>
            <div style={{ fontSize: 42, fontWeight: 800, color: scoreColor(run?.avg_score ?? 0), lineHeight: 1 }}>{run?.avg_score ?? '—'}</div>
            <div className="muted" style={{ fontSize: 11 }}>estate score / 100</div>
            <span className="badge" style={{ marginTop: 9, display: 'inline-block', background: onTrack ? '#E7F0DC' : '#FAEEDA', color: onTrack ? '#2F5310' : '#854F0B' }}>{onTrack ? '✓ On track to conformant' : '⚠ Action required'}</span>
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <button className="exportbtn" onClick={() => run?.id && openReport(run.id)}>⤓ Download full conformance report (PDF)</button>
        </div>
      </section>

      <div className="metrics">
        <div className="metric"><span>ready to publish</span><b>{ready.length}</b></div>
        <div className="metric"><span>published</span><b style={{ color: pubStarted ? '#3B6D11' : '#9AA1B4' }}>{pubStarted ? publishedCount : 0}</b></div>
        <div className="metric"><span>replaced in place</span><b style={{ color: pubStarted ? undefined : '#9AA1B4' }}>{Object.keys(done).length}</b></div>
        <div className="metric"><span>owners notified</span><b style={{ color: pubStarted ? undefined : '#9AA1B4' }}>{pubStarted ? Object.keys(done).length + certified.length : 0}</b></div>
      </div>

      <details className="panel">
        <summary style={{ cursor: 'pointer', fontWeight: 600, listStyle: 'revert' }}>What “publish” does <span className="muted" style={{ fontWeight: 400 }}>· what happens to every re-validated document</span></summary>
        <div className="pubsteps" style={{ marginTop: 12 }}>
          <div className="pubstep"><b>↺ Replace in place</b><span className="muted">the accessible version takes over the original URL / path</span></div>
          <div className="pubstep"><b>📦 Archive prior version</b><span className="muted">the old file is retained for the audit trail</span></div>
          <div className="pubstep"><b>🏷 Update metadata</b><span className="muted">conformance status + scan date written back to the source</span></div>
          <div className="pubstep"><b>✉ Notify stakeholders</b><span className="muted">the document owner is told it’s now compliant</span></div>
        </div>
      </details>

      <section className="panel">
        <div className="rubrichdr">
          <h2 style={{ margin: 0 }}>Publish queue <span className="muted">· {ready.length} re-validated &amp; certifiable</span></h2>
          <button disabled={readOnly || !ready.length || Object.keys(done).length >= ready.length} title={readOnly ? 'Time-travel replay — switch to the latest scan to publish' : undefined} onClick={publishAll}>Publish all</button>
        </div>
        {ready.length > 8 && (
          <SearchFilterBar ctl={sfP} items={ready} facets={PUB_FACETS} noun="files"
                           placeholder="Search the publish queue…" />
        )}
        {ready.length === 0 ? <p className="muted" style={{ marginTop: 10 }}>Nothing certifiable yet — re-validate fixes in Remediate first.</p> : (
          <div className="publist">
            {shownReady.length === 0 ? <p className="muted">No files match — <button className="ghost small" onClick={sfP.clear}>clear the filters</button></p> : shownReady.map((f) => (
              <div className={`pubrow${done[f.file] ? ' pubdone' : ''}`} key={f.file}>
                <button className="remname" onClick={() => setSel(f)}>{f.file}<span className="muted"> · {f.sourceName} · {f.department}</span></button>
                <span className="badge" style={{ background: '#E7F0DC', color: '#3B6D11' }}>{f.score} / 100</span>
                {done[f.file]
                  ? <span className="okline" style={{ fontSize: 13 }}>✓ published · replaced in place · owner notified</span>
                  : <button className="qbtn approve" disabled={readOnly} title={readOnly ? 'Time-travel replay — switch to the latest scan to publish' : undefined} onClick={() => publish(f.file)}>↺ Replace &amp; publish</button>}
              </div>
            ))}
          </div>
        )}
        {publishedList.length > 0 ? (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>📋 Audit trail · {publishedEntries.length} published</div>
            {publishedEntries.slice(0, 8).map((e) => (
              <div key={e.file} style={{ fontSize: 12.5, padding: '5px 0', borderBottom: '1px solid var(--line)' }}>
                ✓ <b>{e.file}</b> <span className="muted">· replaced in place · prior version archived · owner notified · {fmtPublished(e)}</span>
              </div>
            ))}
            {publishedEntries.length > 8 && <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>+{publishedEntries.length - 8} more</div>}
          </div>
        ) : (
          <p className="muted" style={{ marginTop: 12 }}>Publishing writes the conformance status back to the source and records each change in the audit trail here.</p>
        )}
      </section>
      {sel && <FileDrawer file={sel} scanId={run.id} onClose={() => setSel(null)} />}
    </>
  )
}
