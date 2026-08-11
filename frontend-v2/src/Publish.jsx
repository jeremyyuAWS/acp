import { useState, useEffect } from 'react'
import ScopeBanner from './ScopeBanner.jsx'
import { documentSelection, documentScopeSentence } from './remediableScope.js'
import FileDrawer from './FileDrawer.jsx'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import { openReport, publishFile, publishAllFiles, listHitlQueue } from './api.js'

// Step 9 · Publish. Marks re-validated documents as published: the conformance status
// is recorded in the audit trail and the fixed copy (already in Blob + the Drive
// mirror) becomes the document of record. Source replace-in-place and owner
// notification are roadmap — the UI must not claim them until they're real.
// publish() persists via POST /scans/{sid}/publish.
// readOnly: time-travel replay — publishing must act on the live estate, not a snapshot.
export default function Publish({ run, files = [], certified = [], readOnly = false, onPublish, me,
  triage = {} }) {
  const ready = files.filter((f) => f.compliant)
  const sfP = useSearchFilter('publish')
  const PUB_FACETS = [
    { key: 'type', label: 'Type', get: (f) => (f.file.split('.').pop() || '').toUpperCase() },
    { key: 'department', label: 'Dept', get: (f) => f.department },
    { key: 'source', label: 'Source', get: (f) => f.sourceName },
  ]
  const shownReady = sfP.active ? ready.filter(matchesFilters(sfP, PUB_FACETS, (f) => f.file)) : ready
  const [done, setDone] = useState({})
  const [pubUrls, setPubUrls] = useState({})   // file -> published Drive URL, from POST /publish
  const [publishing, setPublishing] = useState(false)
  const [sel, setSel] = useState(null)
  // Why is the publish queue empty? A remediated file only becomes certifiable once its
  // human-review findings are approved. Fetch the pending HITL queue so the empty state can
  // say "N findings await review — approve them in Review first" instead of a dead-end.
  const [pendingReview, setPendingReview] = useState({ items: 0, files: 0 })
  useEffect(() => {
    let live = true
    if (!run?.id) { setPendingReview({ items: 0, files: 0 }); return }
    listHitlQueue(run.id, 'pending')
      .then((q) => { if (live) setPendingReview({ items: (q || []).length, files: new Set((q || []).map((i) => i.file)).size }) })
      .catch(() => { if (live) setPendingReview({ items: 0, files: 0 }) })
    return () => { live = false }
  }, [run?.id, ready.length])
  const orgLabel = me?.email
    ? me.email.split('@')[1]?.replace(/\.[^.]+$/, '') || me.name || 'your organisation'
    : me?.name || 'your organisation'
  const publish = async (file) => {
    if (done[file]) return
    try {
      const res = await publishFile(run?.id, file)
      const u = res?.published?.find((x) => x.file === file)?.published_url
      if (u) setPubUrls((m) => ({ ...m, [file]: u }))
    } catch { /* best-effort — local state still updates */ }
    setDone((d) => ({ ...d, [file]: true }))
    onPublish?.(file)
  }
  const publishAll = async () => {
    if (publishing) return
    setPublishing(true)
    const pending = ready.filter((f) => !done[f.file]).map((f) => f.file)
    try {
      const res = await publishAllFiles(run?.id, pending)
      const urls = {}
      ;(res?.published || []).forEach((x) => { if (x.published_url) urls[x.file] = x.published_url })
      if (Object.keys(urls).length) setPubUrls((m) => ({ ...m, ...urls }))
    } catch { /* best-effort */ }
    setDone(() => Object.fromEntries(ready.map((f) => [f.file, true])))
    ready.forEach((f) => onPublish?.(f.file))
    setPublishing(false)
  }
  const publishedCount = Object.keys(done).length + certified.length
  const pubStarted = Object.keys(done).length > 0   // zero the outcome cards until the user releases
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
      {/* ABOVE the conformance report, not below it. The artifact this screen produces is a
          compliance record, and "certified" against an unstated scope is a claim nobody can
          check later — so what was assessed is stated before what was concluded. */}
      {/* The document selection reaches THIS screen for the first time. Remediate has always
          honoured it; the screen that produces the compliance record never knew about it, so
          a report could be read as covering an estate that two documents of it were fixed in. */}
      <ScopeBanner run={run} fileCount={files.length}
                   docScope={documentScopeSentence(documentSelection(files, triage))} />
      {/* Release Center — the controlled-release summary. NOT a conformance certificate: ACP's
          automated checks verify WITHIN the selected scope; they cannot certify overall WCAG
          conformance. The estate score and "certifiable/conformant" language are gone for exactly
          that reason, and the PDF is a secondary evidence artifact, not the headline. */}
      <section className="panel" style={{ borderLeft: '4px solid #3B6D11' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 18, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 340px' }}>
            <h2 style={{ margin: 0 }}>🚀 Release Center</h2>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              {orgLabel} · WCAG 2.1 Level AA · {reportDate}
            </div>
            <p style={{ fontSize: 13.5, lineHeight: 1.6, margin: '12px 0 0', maxWidth: 620 }}>
              <b style={{ color: '#3B6D11' }}>{run?.certifiable ?? 0}</b> of <b>{(run?.files ?? 0).toLocaleString()}</b> documents were <b>automatically verified within the selected scope</b> and are ready to release{run?.error ? <> · {run.error} could not be analysed</> : null}. ACP verifies the criteria in scope — it does not certify overall conformance.
            </p>
          </div>
          <div style={{ textAlign: 'right', minWidth: 150, fontSize: 13.5, lineHeight: 1.9 }}>
            <div><b style={{ color: '#3B6D11', fontSize: 17 }}>{ready.length}</b> ready for release</div>
            <div><b style={{ color: pubStarted ? '#3B6D11' : 'var(--muted)', fontSize: 17 }}>{pubStarted ? publishedCount : 0}</b> released</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Policy: create a remediated copy</div>
          </div>
        </div>
        <div style={{ marginTop: 14, fontSize: 12.5 }}>
          <span className="muted">Evidence &amp; reports: </span>
          <button className="linklike" onClick={() => run?.id && openReport(run.id)}>⤓ Download scope-limited report (PDF)</button>
        </div>
      </section>

      <details className="panel">
        <summary style={{ cursor: 'pointer', fontWeight: 600, listStyle: 'revert' }}>What “release” does <span className="muted" style={{ fontWeight: 400 }}>· what happens to every verified document</span></summary>
        <div className="pubsteps" style={{ marginTop: 12 }}>
          <div className="pubstep"><b>✓ Marked released</b><span className="muted">the re-validated fixed copy becomes the document of record</span></div>
          <div className="pubstep"><b>⤓ Fixed copy in Blob</b><span className="muted">the accessible copy lives in ACP Blob storage and the Drive “remediated” mirror</span></div>
          <div className="pubstep"><b>📦 Original untouched</b><span className="muted">the fixed copy is written to a separate “remediated” folder — the source file is never overwritten</span></div>
          <div className="pubstep"><b>🏷 Audit recorded</b><span className="muted">the verified-in-scope status + timestamp are written to the audit log</span></div>
        </div>
      </details>

      <section className="panel">
        <div className="rubrichdr">
          <h2 style={{ margin: 0 }}>Release queue <span className="muted">· {ready.length} verified in scope, ready to release</span></h2>
          <button disabled={readOnly || publishing || !ready.length || Object.keys(done).length >= ready.length} title={readOnly ? 'Time-travel replay — switch to the latest scan to release' : undefined} onClick={publishAll}>{publishing ? 'Releasing…' : `Release all (${ready.length})`}</button>
        </div>
        {ready.length > 8 && (
          <SearchFilterBar ctl={sfP} items={ready} facets={PUB_FACETS} noun="files"
                           placeholder="Search the publish queue…" />
        )}
        {ready.length === 0 ? (
          pendingReview.items > 0 ? (
            <div className="muted" style={{ marginTop: 10, padding: '10px 14px', borderRadius: 9, background: '#FBF1DF', border: '1px solid #EAD9BF', color: '#7A5A12' }}>
              ⚑ <b>{pendingReview.items} finding{pendingReview.items !== 1 ? 's' : ''} await{pendingReview.items === 1 ? 's' : ''} human review</b> across {pendingReview.files} document{pendingReview.files !== 1 ? 's' : ''} — approve {pendingReview.items === 1 ? 'it' : 'them'} in <b>Remediate → step 3 · AI Work Inbox</b> first. A document is verified in scope — and appears here — only once its every review item is approved.
            </div>
          ) : (
            <p className="muted" style={{ marginTop: 10 }}>Nothing verified yet — remediate documents and approve their review items in Remediate first.</p>
          )
        ) : (
          <div className="publist">
            {shownReady.length === 0 ? <p className="muted">No files match — <button className="ghost small" onClick={sfP.clear}>clear the filters</button></p> : shownReady.map((f) => (
              <div className={`pubrow${done[f.file] ? ' pubdone' : ''}`} key={f.file}>
                <button className="remname" onClick={() => setSel(f)}>{f.file}<span className="muted"> · {f.sourceName} · {f.department}</span></button>
                <span className="badge" style={{ background: '#E7F0DC', color: '#3B6D11' }}>{f.score} / 100</span>
                {done[f.file]
                  ? <span className="okline" style={{ fontSize: 13 }}>✓ released · fixed copy in Blob · audit recorded{pubUrls[f.file] && <> · <a href={pubUrls[f.file]} target="_blank" rel="noopener noreferrer">↗ open in Drive</a></>}</span>
                  : <button className="qbtn approve" onClick={() => publish(f.file)} disabled={readOnly || publishing} title={readOnly ? 'Time-travel replay — switch to the latest scan to release' : undefined}>↺ Release</button>}
              </div>
            ))}
          </div>
        )}
        {publishedList.length > 0 ? (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>📋 Audit trail · {publishedEntries.length} released</div>
            {publishedEntries.slice(0, 8).map((e) => (
              <div key={e.file} style={{ fontSize: 12.5, padding: '5px 0', borderBottom: '1px solid var(--line)' }}>
                ✓ <b>{e.file}</b> <span className="muted">· fixed copy in Blob · source not overwritten · audit recorded · {fmtPublished(e)}{pubUrls[e.file] && <> · <a href={pubUrls[e.file]} target="_blank" rel="noopener noreferrer">↗ open in Drive</a></>}</span>
              </div>
            ))}
            {publishedEntries.length > 8 && <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>+{publishedEntries.length - 8} more</div>}
          </div>
        ) : (
          <p className="muted" style={{ marginTop: 12 }}>Releasing writes the fixed copy to the Drive “remediated” folder and records each release in the audit trail here.</p>
        )}
      </section>
      {sel && <FileDrawer file={sel} scanId={run.id} onClose={() => setSel(null)} />}
    </>
  )
}
