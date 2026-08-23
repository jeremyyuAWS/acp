import { useState, useEffect } from 'react'
import ScopeBanner from './ScopeBanner.jsx'
import { documentSelection, documentScopeSentence } from './remediableScope.js'
import FileDrawer from './FileDrawer.jsx'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import { openReport, publishFile, publishAllFiles, listHitlQueue, getSettings, getSourceStatus, rescoreFile } from './api.js'
import { releaseDestination, releaseDestinationPhrase, releaseConfirmLines } from './releasePolicy.js'
import { SET_STATUS, certificationUniverse, releaseSetStatus } from './graduation.js'
import { mirrorState, MIRROR } from './deliveryPolicy.js'

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
  // The REAL release policy, read from the platform settings, so the release summary describes where
  // a copy actually lands instead of a hard-coded guess. Best-effort — if it can't be read we fall
  // back to the always-true half (a durable Blob copy) rather than assert a Drive folder we're
  // unsure of.
  const [settings, setSettings] = useState(null)
  useEffect(() => {
    let live = true
    getSettings().then((s) => { if (live && s) setSettings(s) }).catch(() => {})
    return () => { live = false }
  }, [])
  const ms = mirrorState(settings)
  const driveMirrorEnabled = ms === MIRROR.ON
  const driveMirrorFolder = settings?.drive_mirror_folder?.trim() || 'Remediated'
  const anyDrive = ready.some((f) => f.drive_file_id)
  // A release is confirmed before it runs: { kind: 'all' } or { kind: 'file', file }. The buttons
  // set this; the modal's confirm calls the real publish path below.
  const [confirm, setConfirm] = useState(null)
  useEffect(() => {
    if (!confirm) return
    const onKey = (e) => { if (e.key === 'Escape') setConfirm(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [confirm])
  // Source-staleness (Phase 3): has each file's SOURCE changed in Drive since the scan? Best-effort
  // — a scan with nothing trackable returns all-untracked, and any error leaves the map empty (no
  // badges) rather than blocking the queue. Never marks a file "unchanged" it can't actually verify.
  const [srcStatus, setSrcStatus] = useState({ byFile: {}, stale: 0 })
  const [rescanning, setRescanning] = useState({})
  const loadSourceStatus = () => {
    if (!run?.id) return setSrcStatus({ byFile: {}, stale: 0 })
    getSourceStatus(run.id)
      .then((s) => {
        const byFile = {}
        ;(s?.files || []).forEach((r) => { byFile[r.file] = r })
        setSrcStatus({ byFile, stale: s?.stale_count || 0 })
      })
      .catch(() => setSrcStatus({ byFile: {}, stale: 0 }))
  }
  useEffect(() => {
    loadSourceStatus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, ready.length])
  const srcOf = (f) => srcStatus.byFile[f.file]?.state
  const staleReady = ready.filter((f) => !done[f.file] && srcOf(f) === 'stale')
  const rescanBusy = Object.keys(rescanning).length > 0
  const rescanStale = async () => {
    const targets = staleReady.map((f) => f.file)
    if (!targets.length || rescanBusy) return
    setRescanning(Object.fromEntries(targets.map((f) => [f, true])))
    await Promise.allSettled(targets.map((f) => rescoreFile(run?.id, f)))
    // The re-scan runs on the worker; re-check shortly so the refreshed baselines clear the badges.
    // Honest: this re-checks the sources, it does not block on the job finishing.
    setTimeout(() => { loadSourceStatus(); setRescanning({}) }, 4000)
  }
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
  // W5 — set-level certification status (graduation.js). A release can go out CONDITIONALLY while
  // some in-scope documents are still held; once those held documents are remediated (each is
  // re-validated on its own remediation path — no whole-estate re-scan), the set can GRADUATE to
  // full by releasing the now-verified formerly-held documents. Derived purely from what's already
  // on screen: the certification universe, the session's released map, and externally-certified
  // files. `files` refreshes after a remediation (App refetches on acp:file-remediated), so this
  // recomputes and the graduation offer appears without a reload.
  const setStatus = releaseSetStatus(certificationUniverse(files), done, certified)
  const graduate = async () => {
    if (publishing || setStatus.status !== SET_STATUS.GRADUATABLE || !setStatus.graduatable.length) return
    setPublishing(true)
    const targets = setStatus.graduatable
    try {
      const res = await publishAllFiles(run?.id, targets)
      const urls = {}
      ;(res?.published || []).forEach((x) => { if (x.published_url) urls[x.file] = x.published_url })
      if (Object.keys(urls).length) setPubUrls((m) => ({ ...m, ...urls }))
    } catch { /* best-effort — local state still updates */ }
    setDone((d) => ({ ...d, ...Object.fromEntries(targets.map((f) => [f, true])) }))
    targets.forEach((f) => onPublish?.(f))
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
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Policy: remediated copy → {driveMirrorEnabled && anyDrive ? <>Drive “{driveMirrorFolder}” + Blob</> : 'Blob'}</div>
          </div>
        </div>
        <div style={{ marginTop: 14, fontSize: 12.5 }}>
          <span className="muted">Evidence &amp; reports: </span>
          <button className="linklike" onClick={() => run?.id && openReport(run.id)}>⤓ Download scope-limited report (PDF)</button>
        </div>
      </section>

      {/* W5 — conditional-release → full-certification graduation. Shown only once a release has
          started (setStatus is NONE before that, and this renders nothing). */}
      {setStatus.status === SET_STATUS.CONDITIONAL && (
        <section className="panel" style={{ borderLeft: '4px solid #854F0B' }} aria-label="Conditional release status">
          <b style={{ fontSize: 13.5, color: '#854F0B' }}>◐ Conditionally released</b>
          <p style={{ fontSize: 13, lineHeight: 1.6, margin: '8px 0 0', maxWidth: 680 }}>
            <b>{setStatus.released}</b> of <b>{setStatus.total}</b> in-scope documents are released.
            {setStatus.heldOpen > 0 && <> <b>{setStatus.heldOpen}</b> {setStatus.heldOpen === 1 ? 'document is' : 'documents are'} still <b>held</b> pending remediation.</>}
            {setStatus.verifiedUnreleased > 0 && <> <b>{setStatus.verifiedUnreleased}</b> previously-held {setStatus.verifiedUnreleased === 1 ? 'document has' : 'documents have'} been remediated and can be graduated in below.</>}
          </p>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 8, maxWidth: 680 }}>
            Remediate the held documents (each is re-validated on its own remediation path). This release graduates to <b>fully certified</b> once every held document passes — <b>no whole-estate re-scan required</b>.
          </p>
          {setStatus.verifiedUnreleased > 0 && (
            <button className="qbtn approve" style={{ marginTop: 10 }} disabled={readOnly || publishing}
                    title={readOnly ? 'Time-travel replay — switch to the latest scan to release' : 'Release the remediated formerly-held documents'}
                    onClick={graduate}>
              {publishing ? 'Releasing…' : `↑ Release ${setStatus.verifiedUnreleased} remediated document${setStatus.verifiedUnreleased === 1 ? '' : 's'}`}
            </button>
          )}
        </section>
      )}
      {setStatus.status === SET_STATUS.GRADUATABLE && (
        <section className="panel" style={{ borderLeft: '4px solid #3B6D11', background: '#F3F8EC' }} aria-label="Ready to graduate to full certification">
          <b style={{ fontSize: 13.5, color: '#3B6D11' }}>✓ Ready to graduate to full certification</b>
          <p style={{ fontSize: 13, lineHeight: 1.6, margin: '8px 0 0', maxWidth: 680 }}>
            Every previously-held document has been remediated and re-validated. Release the remaining <b>{setStatus.verifiedUnreleased}</b> {setStatus.verifiedUnreleased === 1 ? 'document' : 'documents'} to promote this conditional release to <b>fully certified</b> — <b>no whole-estate re-scan required</b>.
          </p>
          <button className="qbtn approve" style={{ marginTop: 10 }} disabled={readOnly || publishing}
                  title={readOnly ? 'Time-travel replay — switch to the latest scan to release' : undefined}
                  onClick={graduate}>
            {publishing ? 'Graduating…' : `🎓 Graduate to full certification (release ${setStatus.verifiedUnreleased})`}
          </button>
        </section>
      )}
      {setStatus.status === SET_STATUS.FULL && setStatus.total > 0 && (
        <section className="panel" style={{ borderLeft: '4px solid #3B6D11' }} aria-label="Fully certified">
          <b style={{ fontSize: 13.5, color: '#3B6D11' }}>🎓 Fully certified</b>
          <span className="muted" style={{ fontSize: 13, marginLeft: 8 }}>all {setStatus.total} in-scope documents released.</span>
        </section>
      )}

      {/* Release policy — an HONEST description of what the platform actually does, read from the
          real settings, not a selector for a behaviour ACP can't perform. There is one policy:
          write a corrected COPY; the original is never overwritten. The explainer says plainly why
          replace-in-place isn't on offer. */}
      <section className="panel" style={{ borderLeft: '3px solid #1F5FA8' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <b style={{ fontSize: 13.5 }}>Release policy</b>
          <span style={{ fontSize: 13 }}>
            <span aria-hidden="true" style={{ color: '#1F5FA8' }}>●</span> Remediated copy → {releaseDestinationPhrase({ anyDrive, driveMirrorEnabled, driveMirrorFolder })}
          </span>
        </div>
        <div className="muted" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.6 }}>
          The source file is <b>never overwritten</b>. ACP verifies the criteria in scope — it does not certify overall WCAG conformance.
        </div>
        <details style={{ marginTop: 8 }}>
          <summary className="linklike" style={{ cursor: 'pointer', fontSize: 12.5 }}>Why can’t I replace the original?</summary>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.6, maxWidth: 640 }}>
            Replacing the source file in place is on the roadmap, not built — so ACP doesn’t offer it rather than pretend to. Every release writes a corrected copy to a separate location, which is why your originals are never modified. SharePoint sources are connected read-only, so ACP cannot write back to them at all; those releases are delivered as a Blob download.
          </div>
        </details>
      </section>

      <details className="panel">
        <summary style={{ cursor: 'pointer', fontWeight: 600, listStyle: 'revert' }}>What “release” does <span className="muted" style={{ fontWeight: 400 }}>· what happens to every verified document</span></summary>
        <div className="pubsteps" style={{ marginTop: 12 }}>
          <div className="pubstep"><b>✓ Marked released</b><span className="muted">the re-validated fixed copy becomes the document of record</span></div>
          <div className="pubstep"><b>⤓ Fixed copy in Blob</b><span className="muted">{driveMirrorEnabled && anyDrive ? `the accessible copy lives in ACP Blob storage and the Drive “${driveMirrorFolder}” mirror` : 'the accessible copy lives in ACP Blob storage'}</span></div>
          <div className="pubstep"><b>📦 Original untouched</b><span className="muted">the fixed copy is written to a separate “remediated” folder — the source file is never overwritten</span></div>
          <div className="pubstep"><b>🏷 Audit recorded</b><span className="muted">the verified-in-scope status + timestamp are written to the audit log</span></div>
        </div>
      </details>

      <section className="panel">
        <div className="rubrichdr">
          <h2 style={{ margin: 0 }}>Release queue <span className="muted">· {ready.length} verified in scope, ready to release</span></h2>
          <button disabled={readOnly || publishing || !ready.length || Object.keys(done).length >= ready.length} title={readOnly ? 'Time-travel replay — switch to the latest scan to release' : undefined} onClick={() => setConfirm({ kind: 'all' })}>{publishing ? 'Releasing…' : `Release all (${ready.length})`}</button>
        </div>
        {staleReady.length > 0 && (
          <div style={{ marginTop: 10, padding: '10px 14px', borderRadius: 9, background: '#FDECEC', border: '1px solid #E9A8A8', color: '#8A1F1F', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span>⚠ <b>{staleReady.length} document{staleReady.length !== 1 ? 's' : ''}</b> changed at the source in Drive since this scan — re-scan before releasing, or a released fix may be built on an out-of-date version.</span>
            <button className="ghost small" disabled={readOnly || rescanBusy} onClick={rescanStale}>
              {rescanBusy ? 'Re-scanning…' : `↻ Re-scan changed sources (${staleReady.length})`}
            </button>
          </div>
        )}
        {ready.length > 8 && (
          <SearchFilterBar ctl={sfP} items={ready} facets={PUB_FACETS} noun="files"
                           placeholder="Search the publish queue…" />
        )}
        {ready.length === 0 ? (
          pendingReview.items > 0 ? (
            <div className="muted" style={{ marginTop: 10, padding: '10px 14px', borderRadius: 9, background: '#FBF1DF', border: '1px solid #EAD9BF', color: '#7A5A12' }}>
              ⚑ <b>{pendingReview.items} finding{pendingReview.items !== 1 ? 's' : ''} await{pendingReview.items === 1 ? 's' : ''} human review</b> across {pendingReview.files} document{pendingReview.files !== 1 ? 's' : ''} — approve {pendingReview.items === 1 ? 'it' : 'them'} in <b>Remediate → step 3 · Review queue</b> first. A document is verified in scope — and appears here — only once its every review item is approved.
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
                <span className="muted" title="Where this document’s corrected copy will be written" style={{ fontSize: 11.5, whiteSpace: 'nowrap' }}>→ {releaseDestination({ driveFileId: f.drive_file_id, driveMirrorEnabled, driveMirrorFolder }).label}</span>
                {srcOf(f) === 'stale' && <span title="The source file in Drive changed after this scan — re-scan before releasing" style={{ fontSize: 11.5, whiteSpace: 'nowrap', color: '#8A1F1F', fontWeight: 600 }}>⚠ source changed</span>}
                {srcOf(f) === 'unavailable' && <span className="muted" title="ACP could not read the source now (moved, deleted, or access lost)" style={{ fontSize: 11.5, whiteSpace: 'nowrap' }}>source unreachable</span>}
                {done[f.file]
                  ? <span className="okline" style={{ fontSize: 13 }}>✓ released · fixed copy in Blob · audit recorded{pubUrls[f.file] && <> · <a href={pubUrls[f.file]} target="_blank" rel="noopener noreferrer">↗ open in Drive</a></>}</span>
                  : <button className="qbtn approve" onClick={() => setConfirm({ kind: 'file', file: f.file })} disabled={readOnly || publishing} title={readOnly ? 'Time-travel replay — switch to the latest scan to release' : undefined}>↺ Release</button>}
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
          <p className="muted" style={{ marginTop: 12 }}>{driveMirrorEnabled ? `Releasing writes the fixed copy to the Drive “${driveMirrorFolder}” folder and Azure Blob storage and records each release in the audit trail here.` : 'Releasing writes the fixed copy to Azure Blob storage and records each release in the audit trail here.'}</p>
        )}
      </section>
      {sel && <FileDrawer file={sel} scanId={run.id} onClose={() => setSel(null)} />}

      {/* Confirmation before a release runs. States, in checkable terms, exactly what will happen —
          destination, that the original is untouched, the audit entry, and that this is not a
          conformance certificate. Escape or a backdrop click cancels. */}
      {confirm && (() => {
        const isAll = confirm.kind === 'all'
        const targets = isAll ? ready.filter((f) => !done[f.file]) : ready.filter((f) => f.file === confirm.file)
        const cnt = isAll ? targets.length : 1
        const batchAnyDrive = targets.some((f) => f.drive_file_id)
        const lines = releaseConfirmLines({ count: cnt, anyDrive: batchAnyDrive, driveMirrorEnabled, driveMirrorFolder })
        const onGo = () => { setConfirm(null); if (isAll) publishAll(); else publish(confirm.file) }
        return (
          <div role="dialog" aria-modal="true" aria-label="Confirm release" onClick={() => setConfirm(null)}
               style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.42)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 20 }}>
            <div onClick={(e) => e.stopPropagation()}
                 style={{ background: 'var(--panel, #fff)', color: 'var(--ink)', border: '1px solid var(--line)', borderRadius: 12, padding: '20px 22px', maxWidth: 520, width: '100%', boxShadow: '0 12px 40px rgba(0,0,0,0.25)' }}>
              <h3 style={{ margin: '0 0 12px' }}>{isAll ? `Release ${cnt} document${cnt === 1 ? '' : 's'}?` : `Release ${confirm.file}?`}</h3>
              <ul style={{ margin: '0 0 18px', paddingLeft: 18, fontSize: 13.5, lineHeight: 1.65 }}>
                {lines.map((l, i) => <li key={i}>{l}</li>)}
              </ul>
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button className="ghost" onClick={() => setConfirm(null)}>Cancel</button>
                <button className="qbtn approve" onClick={onGo} disabled={cnt === 0}>{isAll ? `Release ${cnt}` : 'Release'}</button>
              </div>
            </div>
          </div>
        )
      })()}
    </>
  )
}
