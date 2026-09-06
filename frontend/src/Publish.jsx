import { useState, useEffect, useRef } from 'react'
import ScopeBanner from './ScopeBanner.jsx'
import { documentSelection, documentScopeSentence } from './remediableScope.js'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import { openReport, publishFile, publishAllFiles, getReleaseStatus, getReleaseManifest, listHitlQueue, getSettings, getSourceStatus, rescoreFile, downloadReleasePackage } from './api.js'
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
  const [releaseFolder, setReleaseFolder] = useState(null)
  const [releaseId, setReleaseId] = useState(null)
  const [releaseFolders, setReleaseFolders] = useState([])
  const [releaseResults, setReleaseResults] = useState({})
  const [releaseAnnouncement, setReleaseAnnouncement] = useState('')
  const [manifestError, setManifestError] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [builderStep, setBuilderStep] = useState(1)
  const [deliveryMethod, setDeliveryMethod] = useState('publish')
  const [packageName, setPackageName] = useState('')
  const [releaseFolderName, setReleaseFolderName] = useState('')
  const [selectedFiles, setSelectedFiles] = useState(() => new Set())
  const builderRef = useRef(null)
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
  const releaseProvider = run?.source
  const anyDrive = releaseProvider === 'drive' && ready.some((f) => f.drive_file_id)
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
  const publishableReady = ready.filter((f) => !done[f.file] && srcOf(f) !== 'stale')
  const selectableReady = ready.filter((f) => srcOf(f) !== 'stale')
  const selectedReady = selectableReady.filter((f) => selectedFiles.has(f.file))
  const selectedPublishable = selectedReady.filter((f) => !done[f.file])
  useEffect(() => {
    setSelectedFiles((old) => {
      const eligible = new Set(selectableReady.map((f) => f.file))
      if (old.size === 0) return eligible
      const next = new Set([...old].filter((file) => eligible.has(file)))
      return next.size ? next : eligible
    })
    // Source freshness and release completion can change the eligible set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, ready.length, srcStatus.stale, Object.keys(done).length])
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
  const rememberRelease = (res, expectedFiles = []) => {
    if (res?.release_id) setReleaseId(res.release_id)
    const roots = res?.release_folders || res?.roots || []
    const mappedRoots = roots.map((root) => ({
      id: root.folder_id || root.id, name: root.folder_name || root.name,
      url: root.folder_url || root.url, location: root.provider_location,
    })).filter((root) => root.id)
    if (mappedRoots.length) setReleaseFolders(mappedRoots)
    if (res?.release_folder_name || mappedRoots[0]) setReleaseFolder({
      id: res.release_folder_id || mappedRoots[0]?.id,
      name: res.release_folder_name || mappedRoots[0]?.name,
      url: res.release_folder_url || mappedRoots[0]?.url,
      createdAt: res.created_at || new Date().toISOString(),
    })
    const reported = res?.published || []
    // Pre-structured-release servers returned no per-document status. Preserve the existing
    // callback contract for that response shape during rolling deploys; a new response always
    // carries release_id, so an explicit empty/failed result is never promoted to success.
    const rows = reported.length || res?.release_id
      ? reported
      : expectedFiles.map((file) => ({ file, status: 'published', created: false }))
    setReleaseResults((old) => ({ ...old,
      ...Object.fromEntries(rows.map((row) => [row.file, row])),
    }))
    const successful = rows.filter((row) => row.status === 'published')
    if (successful.length) {
      setDone((old) => ({ ...old,
        ...Object.fromEntries(successful.map((row) => [row.file, true])),
      }))
      setPubUrls((old) => ({ ...old,
        ...Object.fromEntries(successful.filter((row) => row.published_url)
          .map((row) => [row.file, row.published_url])),
      }))
    }
    const failed = rows.filter((row) => row.status === 'failed').length
    const inFlight = rows.filter((row) => row.status === 'queued' || row.status === 'running').length
    setReleaseAnnouncement(inFlight
      ? `${inFlight} corrected ${inFlight === 1 ? 'copy is' : 'copies are'} being released.`
      : `${successful.length} corrected ${successful.length === 1 ? 'copy' : 'copies'} released${failed ? `; ${failed} need attention` : ''}.`)
    return successful
  }
  const applyReleaseStatus = (status) => rememberRelease({
    ...status, release_folders: status.roots,
    published: (status.documents || []).map((row) => ({
      file: row.file, status: row.status,
      original_relative_path: row.source_relative_path,
      released_relative_path: row.destination_relative_path,
      released_document_id: row.released_document_id,
      published_url: row.released_document_url,
      corrected_checksum: row.corrected_checksum,
      verification: row.verification, published_at: row.published_at,
      created: !!row.created_result,
      failure_category: row.failure_category, explanation: row.explanation,
    })),
  })
  const followSharePointRelease = async (expectedFiles) => {
    // The backend queues one durable job per SharePoint document. Follow the persisted release,
    // not the originating request: navigation, a worker restart, or a replica change cannot erase
    // progress. The normal load effect below restores the same state after a page reload.
    for (let attempt = 0; attempt < 180; attempt += 1) {
      const status = await getReleaseStatus(run.id)
      applyReleaseStatus(status)
      const rows = status?.documents || []
      const pending = rows.some((row) => row.status === 'queued' || row.status === 'running')
      if (!pending && rows.length >= expectedFiles.length) return status
      await new Promise((resolve) => setTimeout(resolve, 2000))
    }
    setReleaseAnnouncement('Release is still running safely in the background. You may leave this page and return later.')
    return null
  }
  useEffect(() => {
    let live = true
    if (!run?.id) return undefined
    getReleaseStatus(run.id).then((status) => {
      if (!live || !status?.release_id) return
      applyReleaseStatus(status)
    }).catch(() => {})
    return () => { live = false }
    // Release state is durable; reload it when the selected scan changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id])
  const publish = async (file) => {
    if (done[file]) return
    try {
      const res = await publishFile(run?.id, file)
      const successful = rememberRelease(res, [file])
      if (releaseProvider === 'sharepoint' && res?.queued) {
        const status = await followSharePointRelease([file])
        const completed = (status?.documents || []).find((row) => row.file === file && row.status === 'published')
        if (completed) onPublish?.(file)
        return
      }
      if (successful.some((row) => row.file === file)) onPublish?.(file)
    } catch { setReleaseAnnouncement('Release failed. The original file is unchanged; retry when the connection is available.') }
  }
  const publishAll = async (fileNames = null, preferredFolderName = '') => {
    if (publishing) return
    setPublishing(true)
    const requested = fileNames ? new Set(fileNames) : null
    const pending = ready.filter((f) => !done[f.file] && (!requested || requested.has(f.file))).map((f) => f.file)
    try {
      const res = preferredFolderName
        ? await publishAllFiles(run?.id, pending, preferredFolderName)
        : await publishAllFiles(run?.id, pending)
      const successful = rememberRelease(res, pending)
      if (releaseProvider === 'sharepoint' && res?.queued) {
        const status = await followSharePointRelease(pending)
        ;(status?.documents || []).filter((row) => row.status === 'published')
          .forEach((row) => onPublish?.(row.file))
        setPublishing(false)
        return
      }
      successful.forEach((row) => onPublish?.(row.file))
    } catch { /* best-effort */ }
    setPublishing(false)
  }
  const downloadSelected = async () => {
    if (downloading || !selectedReady.length) return
    setDownloading(true)
    try {
      await downloadReleasePackage(run?.id, selectedReady.map((file) => file.file), packageName)
      setReleaseAnnouncement(`Package downloaded with ${selectedReady.length} corrected ${selectedReady.length === 1 ? 'file' : 'files'} and a release manifest.`)
    } catch (error) {
      setReleaseAnnouncement(error?.message || 'The corrected files could not be packaged for download.')
    }
    setDownloading(false)
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
      const successful = rememberRelease(res, targets)
      if (releaseProvider === 'sharepoint' && res?.queued) {
        const status = await followSharePointRelease(targets)
        ;(status?.documents || []).filter((row) => row.status === 'published')
          .forEach((row) => onPublish?.(row.file))
        setPublishing(false)
        return
      }
      successful.forEach((row) => onPublish?.(row.file))
    } catch { /* best-effort — local state still updates */ }
    setPublishing(false)
  }
  const publishedCount = Math.min(ready.length, Object.keys(done).length + certified.length)
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
  const sourcePath = (f) => f.source_relative_path || f.parent_folder || f.file
  const sourceFolder = (f) => {
    const parts = sourcePath(f).replace(/\\/g, '/').split('/')
    return parts.length > 1 ? parts.slice(0, -1).join('/') : 'Source root'
  }
  const groupedReady = shownReady.reduce((groups, file) => {
    const folder = sourceFolder(file)
    return { ...groups, [folder]: [...(groups[folder] || []), file] }
  }, {})
  const selectedResult = sel ? releaseResults[sel.file] : null
  const failedCount = Object.values(releaseResults).filter((row) => row.status === 'failed').length
  const failedReady = ready.filter((f) => !done[f.file] && releaseResults[f.file]?.status === 'failed' && srcOf(f) !== 'stale')
  const downloadReleaseManifest = async () => {
    setManifestError('')
    try {
      const payload = await getReleaseManifest(run.id)
      const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url; link.download = `acp-release-${run?.id || 'manifest'}.json`; link.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setManifestError(e?.message || 'The release manifest could not be downloaded.')
    }
  }
  const startRelease = () => {
    setBuilderStep(1)
    window.requestAnimationFrame(() => {
      builderRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      builderRef.current?.focus({ preventScroll: true })
    })
  }
  const chooseDelivery = () => {
    if (!selectedPublishable.length) setDeliveryMethod('download')
    setBuilderStep(2)
  }
  const validateDeliveryName = (value, label) => {
    const name = value.trim().replace(label === 'ZIP filename' ? /\.zip$/i : /$^/, '').trim()
    if (!name) return ''
    if (name.endsWith('.')) return `${label} cannot end with a period.`
    if (name.length > 100) return `${label} must be 100 characters or fewer.`
    if (/[<>:"/\\|?*\u0000-\u001f\u007f]/.test(name)) return `${label} contains a character that cannot be used in a file or folder name.`
    return ''
  }
  const deliveryNameError = deliveryMethod === 'download'
    ? validateDeliveryName(packageName, 'ZIP filename')
    : releaseFolder ? '' : validateDeliveryName(releaseFolderName, 'Release folder name')
  const reviewFailedRelease = () => {
    setSelectedFiles(new Set(failedReady.map((f) => f.file)))
    setDeliveryMethod('publish')
    setBuilderStep(3)
    window.requestAnimationFrame(() => {
      builderRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      builderRef.current?.focus({ preventScroll: true })
    })
  }

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
      <section className="panel release-overview" aria-labelledby="release-title">
        <div className="release-overview__heading">
          <div>
            <h2 id="release-title" style={{ margin: 0 }}>Release</h2>
            <p className="muted" style={{ margin: '5px 0 0' }}>Deliver verified, remediated copies without changing the originals.</p>
          </div>
          <div className="release-overview__actions">
            <button className="ghost" onClick={() => run?.id && openReport(run.id)}>Download report</button>
            <button className="qbtn approve" disabled={!selectableReady.length} onClick={startRelease}>Start a release</button>
          </div>
        </div>
        <div className="release-metrics" aria-label="Release status overview">
          <div><b>{publishableReady.length}</b><span>Ready</span></div>
          <div><b>{pendingReview.files}</b><span>Need review</span></div>
          <div className={staleReady.length ? 'release-metric--warn' : ''}><b>{staleReady.length}</b><span>Source changed</span></div>
          <div><b>{pubStarted ? publishedCount : 0}</b><span>Released</span></div>
          <div className={failedCount ? 'release-metric--warn' : ''}><b>{failedCount}</b><span>Failed</span></div>
        </div>
      </section>
      {/* Release Center — the controlled-release summary. NOT a conformance certificate: ACP's
          automated checks verify WITHIN the selected scope; they cannot certify overall WCAG
          conformance. The estate score and "certifiable/conformant" language are gone for exactly
          that reason, and the PDF is a secondary evidence artifact, not the headline. */}
      <details className="panel release-record" style={{ borderLeft: '4px solid var(--success-fg)' }}>
        <summary className="release-record__summary">
          <span><b>Release details and evidence</b><small>{orgLabel} · WCAG 2.1 Level AA · {reportDate}</small></span>
          <span>{ready.length} ready · {pubStarted ? publishedCount : 0} released</span>
        </summary>
        <div className="release-record__body">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 18, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 340px' }}>
            <h2 style={{ margin: 0 }}>🚀 Release Center</h2>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              {orgLabel} · WCAG 2.1 Level AA · {reportDate}
            </div>
            <p style={{ fontSize: 13.5, lineHeight: 1.6, margin: '12px 0 0', maxWidth: 620 }}>
              <b style={{ color: 'var(--success-fg)' }}>{run?.certifiable ?? 0}</b> of <b>{(run?.files ?? 0).toLocaleString()}</b> documents were <b>automatically verified within the selected scope</b> and are ready to release{run?.error ? <> · {run.error} could not be analysed</> : null}. ACP verifies the criteria in scope — it does not certify overall conformance.
            </p>
          </div>
          <div style={{ textAlign: 'right', minWidth: 150, fontSize: 13.5, lineHeight: 1.9 }}>
            <div><b style={{ color: 'var(--success-fg)', fontSize: 17 }}>{ready.length}</b> ready for release</div>
            <div><b style={{ color: pubStarted ? 'var(--success-fg)' : 'var(--muted)', fontSize: 17 }}>{pubStarted ? publishedCount : 0}</b> released</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Policy: remediated copy → {driveMirrorEnabled && anyDrive ? <>Drive “{driveMirrorFolder}” + Blob</> : 'Blob'}</div>
          </div>
        </div>
        <div style={{ marginTop: 14, fontSize: 12.5 }}>
          <span className="muted">Evidence &amp; reports: </span>
          <button className="linklike" onClick={() => run?.id && openReport(run.id)}>⤓ Download scope-limited report (PDF)</button>
        </div>
        <div aria-label="Release destination" style={{ marginTop: 14, padding: 14,
          border: '1px solid var(--line)', borderRadius: 10, display: 'grid', gap: 6 }}>
          <b>{releaseFolder?.name || 'Remediated / timestamp created when release starts'}</b>
          <span className="muted">{run?.sourceName || run?.source || 'Connected source'} · {releaseFolder?.createdAt ? new Date(releaseFolder.createdAt).toLocaleString() : 'Not created yet'}</span>
          <span><b>{publishedCount}</b> published · <b>{Math.max(0, ready.length - Object.keys(done).length)}</b> remaining · <b>{failedCount}</b> failed</span>
          <span>Original files are unchanged.</span>
          {releaseFolders.length <= 1 && releaseFolder?.url && <a href={releaseFolder.url} target="_blank" rel="noopener noreferrer" aria-label={`Open release folder ${releaseFolder.name}`}>Open release folder ↗</a>}
          {releaseFolders.length > 1 && <div style={{ display: 'grid', gap: 4 }}>
            {releaseFolders.filter((folder) => folder.url).map((folder) => <a key={folder.location || folder.id} href={folder.url} target="_blank" rel="noopener noreferrer" aria-label={`Open release folder ${folder.name} in ${folder.location || 'connected source'}`}>Open {folder.location?.replace(/^graph:/, 'library ') || folder.name} ↗</a>)}
          </div>}
        </div>
        <div className="sr-only" aria-live="polite">{releaseAnnouncement}</div>
        </div>
      </details>

      {/* W5 — conditional-release → full-certification graduation. Shown only once a release has
          started (setStatus is NONE before that, and this renders nothing). */}
      {setStatus.status === SET_STATUS.CONDITIONAL && (
        <section className="panel" style={{ borderLeft: '4px solid var(--warn-fg)' }} aria-label="Conditional release status">
          <b style={{ fontSize: 13.5, color: 'var(--warn-fg)' }}>◐ Conditionally released</b>
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
                    title={readOnly ? 'Scan History replay — switch to the latest scan to release' : 'Release the remediated formerly-held documents'}
                    onClick={graduate}>
              {publishing ? 'Releasing…' : `↑ Release ${setStatus.verifiedUnreleased} remediated document${setStatus.verifiedUnreleased === 1 ? '' : 's'}`}
            </button>
          )}
        </section>
      )}
      {setStatus.status === SET_STATUS.GRADUATABLE && (
        <section className="panel" style={{ borderLeft: '4px solid var(--success-fg)', background: '#F3F8EC' }} aria-label="Ready to graduate to full certification">
          <b style={{ fontSize: 13.5, color: 'var(--success-fg)' }}>✓ Ready to graduate to full certification</b>
          <p style={{ fontSize: 13, lineHeight: 1.6, margin: '8px 0 0', maxWidth: 680 }}>
            Every previously-held document has been remediated and re-validated. Release the remaining <b>{setStatus.verifiedUnreleased}</b> {setStatus.verifiedUnreleased === 1 ? 'document' : 'documents'} to promote this conditional release to <b>fully certified</b> — <b>no whole-estate re-scan required</b>.
          </p>
          <button className="qbtn approve" style={{ marginTop: 10 }} disabled={readOnly || publishing}
                  title={readOnly ? 'Scan History replay — switch to the latest scan to release' : undefined}
                  onClick={graduate}>
            {publishing ? 'Graduating…' : `🎓 Graduate to full certification (release ${setStatus.verifiedUnreleased})`}
          </button>
        </section>
      )}
      {setStatus.status === SET_STATUS.FULL && setStatus.total > 0 && (
        <section className="panel" style={{ borderLeft: '4px solid var(--success-fg)' }} aria-label="Fully certified">
          <b style={{ fontSize: 13.5, color: 'var(--success-fg)' }}>🎓 Fully certified</b>
          <span className="muted" style={{ fontSize: 13, marginLeft: 8 }}>all {setStatus.total} in-scope documents released.</span>
        </section>
      )}

      {/* Release policy — an HONEST description of what the platform actually does, read from the
          real settings, not a selector for a behaviour ACP can't perform. There is one policy:
          write a corrected COPY; the original is never overwritten. The explainer says plainly why
          replace-in-place isn't on offer. */}
      <details className="panel" style={{ borderLeft: '3px solid var(--info-fg)' }}>
        <summary style={{ cursor: 'pointer' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <b style={{ fontSize: 13.5 }}>Release policy</b>
          <span style={{ fontSize: 13 }}>
            <span aria-hidden="true" style={{ color: 'var(--info-fg)' }}>●</span> Remediated copy → {releaseDestinationPhrase({ provider: releaseProvider, anyDrive, driveMirrorEnabled, driveMirrorFolder })}
          </span>
        </div>
        </summary>
        <div className="muted" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.6 }}>
          The source file is <b>never overwritten</b>. ACP verifies the criteria in scope — it does not certify overall WCAG conformance.
        </div>
        <details style={{ marginTop: 8 }}>
          <summary className="linklike" style={{ cursor: 'pointer', fontSize: 12.5 }}>Why can’t I replace the original?</summary>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.6, maxWidth: 640 }}>
            Replacing the source file in place is not part of Release. ACP writes corrected copies to a separate timestamped location in Google Drive or each source SharePoint library, which is why your originals are never modified.
          </div>
        </details>
      </details>

      <details className="panel">
        <summary style={{ cursor: 'pointer', fontWeight: 600, listStyle: 'revert' }}>What “release” does <span className="muted" style={{ fontWeight: 400 }}>· what happens to every verified document</span></summary>
        <div className="pubsteps" style={{ marginTop: 12 }}>
          <div className="pubstep"><b>✓ Marked released</b><span className="muted">the re-validated fixed copy becomes the document of record</span></div>
          <div className="pubstep"><b>⤓ Fixed copy in Blob</b><span className="muted">{driveMirrorEnabled && anyDrive ? `the accessible copy lives in ACP Blob storage and the Drive “${driveMirrorFolder}” mirror` : 'the accessible copy lives in ACP Blob storage'}</span></div>
          <div className="pubstep"><b>📦 Original untouched</b><span className="muted">the fixed copy is written to a separate “remediated” folder — the source file is never overwritten</span></div>
          <div className="pubstep"><b>🏷 Audit recorded</b><span className="muted">the verified-in-scope status + timestamp are written to the audit log</span></div>
        </div>
      </details>

      <section className="panel release-workspace" ref={builderRef} tabIndex={-1} aria-labelledby="release-workspace-title">
        <div className="rubrichdr">
          <h2 id="release-workspace-title" style={{ margin: 0 }}>Choose files <span className="muted">· {selectedReady.length} of {selectableReady.length} selected</span></h2>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="ghost small" disabled={!selectableReady.length} onClick={() => setSelectedFiles(new Set(selectableReady.map((f) => f.file)))}>Select all</button>
            <button className="ghost small" disabled={!selectedReady.length} onClick={() => setSelectedFiles(new Set())}>Clear</button>
          </div>
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
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', border: '1px solid var(--line)', borderRadius: 10, overflow: 'hidden' }}>
            <div className="publist" aria-label="Documents grouped by source folder" style={{ borderRight: '1px solid var(--line)', padding: 10 }}>
            {shownReady.length === 0 ? <p className="muted">No files match — <button className="ghost small" onClick={sfP.clear}>clear the filters</button></p> : Object.entries(groupedReady).map(([folder, folderFiles]) => (
              <div key={folder}>
                <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--muted)', padding: '8px 6px 4px' }}>{folder}</div>
                {folderFiles.map((f) => <div className={`pubrow release-file-row${done[f.file] ? ' pubdone' : ''}`} key={f.file}>
                <input className="release-file-check" type="checkbox" aria-label={`Select ${f.file}`} checked={selectedFiles.has(f.file)}
                       disabled={srcOf(f) === 'stale'}
                       onChange={(e) => setSelectedFiles((old) => { const next = new Set(old); if (e.target.checked) next.add(f.file); else next.delete(f.file); return next })} />
                <div className="release-file-main">
                  <button className="remname" onClick={() => setSel(f)}>{f.file}</button>
                  <div className="release-file-meta">
                    <span>{f.sourceName || 'Connected source'}{f.department ? ` · ${f.department}` : ''}</span>
                    <span className="badge" style={{ background: 'var(--success-bg)', color: 'var(--success-fg)' }}>{f.score} / 100</span>
                    <span className="release-file-destination" title="Where this document’s corrected copy will be written">→ {releaseDestination({ provider: releaseProvider, driveFileId: f.drive_file_id, driveMirrorEnabled, driveMirrorFolder }).label}</span>
                    {srcOf(f) === 'stale' && <span className="release-file-warning" title="The source file changed after this scan — re-scan before releasing">⚠ source changed</span>}
                    {srcOf(f) === 'unavailable' && <span className="release-file-warning" title="ACP could not read the source now (moved, deleted, or access lost)">source unreachable</span>}
                  </div>
                  {done[f.file] && <div className="release-file-outcome">✓ Released · audit recorded{pubUrls[f.file] && <> · <a href={pubUrls[f.file]} target="_blank" rel="noopener noreferrer">Open in Drive ↗</a></>}</div>}
                </div>
                <button className="ghost small release-file-action" onClick={() => setSel(f)}>View details</button>
              </div>)}
              </div>
            ))}
            </div>
            <div aria-label="Selected document release details" style={{ padding: 18 }}>
              {sel ? <>
                <h3 style={{ marginTop: 0 }}>{sel.file}</h3>
                <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '8px 14px', fontSize: 13 }}>
                  <dt>Release status</dt><dd>{selectedResult?.status || (done[sel.file] ? 'published' : 'ready')}</dd>
                  <dt>Original path</dt><dd>{selectedResult?.original_relative_path || sourcePath(sel)}</dd>
                  <dt>Destination path</dt><dd>{selectedResult?.released_relative_path || `Remediated / ${releaseFolder?.name || '<release timestamp>'} / ${sourcePath(sel)}`}</dd>
                  <dt>Verification</dt><dd>{selectedResult?.verification || 'Pending release'}</dd>
                </dl>
                {selectedResult?.status === 'failed' && <div role="alert" style={{ marginTop: 14, color: 'var(--error-fg-strong)' }}><b>Needs attention:</b> {selectedResult.explanation}</div>}
                {selectedResult?.published_url && <a href={selectedResult.published_url} target="_blank" rel="noopener noreferrer" aria-label={`Open released document ${sel.file}`}>Open released document ↗</a>}
                <details style={{ marginTop: 16 }}><summary>Audit history</summary><p className="muted">{selectedResult?.published_at ? `Released ${new Date(selectedResult.published_at).toLocaleString()} · ${selectedResult.created ? 'created' : 'reused'}` : 'No release event yet.'}</p></details>
              </> : <p className="muted">Select a document to see its original path, destination, verification, and audit history.</p>}
            </div>
          </div>
        )}
        {ready.length > 0 && (
          <div className="release-builder" aria-label="Release builder">
            <div className="release-builder__steps" aria-label="Release steps">
              <span className={builderStep === 1 ? 'active' : 'complete'} aria-current={builderStep === 1 ? 'step' : undefined}>1 <b>Choose files</b></span>
              <span className={builderStep === 2 ? 'active' : builderStep > 2 ? 'complete' : ''} aria-current={builderStep === 2 ? 'step' : undefined}>2 <b>Choose delivery</b></span>
              <span className={builderStep === 3 ? 'active' : ''} aria-current={builderStep === 3 ? 'step' : undefined}>3 <b>Review</b></span>
            </div>
            {builderStep === 1 ? (
              <div className="release-builder__continue">
                <span className="muted">{selectedReady.length ? `${selectedReady.length} corrected ${selectedReady.length === 1 ? 'file is' : 'files are'} ready.` : 'Select at least one ready file.'}</span>
                <button className="qbtn approve" disabled={!selectedReady.length} onClick={chooseDelivery}>Choose delivery</button>
              </div>
            ) : builderStep === 2 ? <>
              <fieldset className="release-methods">
                <legend>How do you want to receive the corrected files?</legend>
                <label className={`${deliveryMethod === 'publish' ? 'selected' : ''}${!selectedPublishable.length ? ' disabled' : ''}`}>
                  <input type="radio" name="delivery-method" value="publish" checked={deliveryMethod === 'publish'} disabled={!selectedPublishable.length} onChange={() => setDeliveryMethod('publish')} />
                  <b>Publish copies</b>
                  <span>{selectedPublishable.length ? `${selectedPublishable.length} unreleased · ${releaseDestinationPhrase({ provider: releaseProvider, anyDrive, driveMirrorEnabled, driveMirrorFolder })}` : 'Every selected file is already published. Choose download to retrieve another copy.'}</span>
                </label>
                <label className={deliveryMethod === 'download' ? 'selected' : ''}>
                  <input type="radio" name="delivery-method" value="download" checked={deliveryMethod === 'download'} onChange={() => setDeliveryMethod('download')} />
                  <b>Download ZIP package</b>
                  <span>One ZIP with the source folder structure and a release manifest.</span>
                </label>
                <div className="release-methods__resting">
                  <b>Not ready to deliver?</b><span>Do nothing—corrected copies remain safely stored in ACP.</span>
                </div>
              </fieldset>
              <div className="release-name-field">
                {deliveryMethod === 'download' ? <>
                  <label htmlFor="release-package-name"><b>ZIP filename</b> <span>Optional</span></label>
                  <input id="release-package-name" value={packageName} onChange={(e) => setPackageName(e.target.value)} placeholder={`acp-release-${run?.id || 'scan'}.zip`} aria-describedby="release-name-help release-name-error" />
                  <small id="release-name-help">“.zip” is added automatically. Leave blank to use the scan-based name.</small>
                </> : releaseFolder ? <>
                  <label><b>Release folder name</b></label>
                  <div className="release-name-existing">{releaseFolder.name}</div>
                  <small>This scan’s release has started, so retries keep the same destination.</small>
                </> : <>
                  <label htmlFor="release-folder-name"><b>Release folder name</b> <span>Optional</span></label>
                  <input id="release-folder-name" value={releaseFolderName} onChange={(e) => setReleaseFolderName(e.target.value)} placeholder="Automatic: release date and time" aria-describedby="release-name-help release-name-error" />
                  <small id="release-name-help">This name becomes permanent when this scan’s first release starts.</small>
                </>}
                {deliveryNameError && <div id="release-name-error" className="release-name-error" role="alert">{deliveryNameError}</div>}
              </div>
              <div className="release-builder__continue release-builder__navigation">
                <button className="ghost" onClick={() => setBuilderStep(1)}>Back to files</button>
                <button className="qbtn approve" disabled={Boolean(deliveryNameError)} onClick={() => setBuilderStep(3)}>Review release</button>
              </div>
            </> : <>
              <div className="release-plan">
                <div>
                  <b>Review your release plan</b>
                  <p>{deliveryMethod === 'publish'
                    ? `${selectedPublishable.length} unreleased corrected ${selectedPublishable.length === 1 ? 'copy' : 'copies'} will be published to ${(releaseFolder?.name || releaseFolderName.trim()) ? `the “${releaseFolder?.name || releaseFolderName.trim()}” release folder` : releaseDestinationPhrase({ provider: releaseProvider, anyDrive, driveMirrorEnabled, driveMirrorFolder })}. Already released files are excluded. Original files will not be changed.`
                    : `${selectedReady.length} corrected ${selectedReady.length === 1 ? 'file' : 'files'} will be packaged in “${packageName.trim().replace(/\.zip$/i, '') || `acp-release-${run?.id || 'scan'}`}.zip” with folder structure and a manifest. Original files will not be changed.`}</p>
                </div>
                <div className="release-plan__actions">
                  <button className="ghost" onClick={() => setBuilderStep(2)}>Back to delivery</button>
                  {deliveryMethod === 'publish'
                    ? <button className="qbtn approve" disabled={readOnly || publishing || !selectedPublishable.length} onClick={() => setConfirm({ kind: 'selected', files: selectedPublishable.map((f) => f.file), folderName: releaseFolder?.name || releaseFolderName.trim() })}>{publishing ? 'Publishing…' : `Publish ${selectedPublishable.length} ${selectedPublishable.length === 1 ? 'copy' : 'copies'}`}</button>
                    : <button className="qbtn approve" disabled={downloading || !selectedReady.length} onClick={downloadSelected}>{downloading ? 'Building package…' : `Download ZIP (${selectedReady.length})`}</button>}
                </div>
              </div>
            </>}
          </div>
        )}
        {failedCount > 0 && (
          <div className="release-outcome release-outcome--partial" role="alert">
            <div>
              <b>{failedCount} corrected {failedCount === 1 ? 'copy needs' : 'copies need'} attention</b>
              <p>Successful files remain published. Retrying sends only the failed copies, so completed work is not duplicated.</p>
              {failedCount > failedReady.length && <p className="release-outcome__blocked">{failedCount - failedReady.length} failed {failedCount - failedReady.length === 1 ? 'file is' : 'files are'} no longer retryable until the changed source is rescanned.</p>}
            </div>
            <button className="qbtn approve" disabled={!failedReady.length || publishing} onClick={reviewFailedRelease}>
              Review and retry failed ({failedReady.length})
            </button>
          </div>
        )}
        {publishedList.length > 0 ? (
          <div style={{ marginTop: 14 }}>
            {Object.keys(done).length === ready.length && ready.length > 0 && <div className="okline" style={{ marginBottom: 10 }}><b>{ready.length} corrected {ready.length === 1 ? 'copy' : 'copies'} released</b>{releaseFolder?.url && <> · <a href={releaseFolder.url} target="_blank" rel="noopener noreferrer">Open release folder ↗</a></>}</div>}
            <button className="ghost small" onClick={downloadReleaseManifest}>Download release manifest</button>
            {manifestError && <div role="alert" style={{ color: 'var(--error-fg-strong)', marginTop: 8 }}>{manifestError}</div>}
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

      {/* Confirmation before a release runs. States, in checkable terms, exactly what will happen —
          destination, that the original is untouched, the audit entry, and that this is not a
          conformance certificate. Escape or a backdrop click cancels. */}
      {confirm && (() => {
        const isBatch = confirm.kind === 'all' || confirm.kind === 'selected'
        const requested = new Set(confirm.files || [])
        const targets = confirm.kind === 'selected' ? ready.filter((f) => requested.has(f.file)) : confirm.kind === 'all' ? ready.filter((f) => !done[f.file]) : ready.filter((f) => f.file === confirm.file)
        const cnt = targets.length
        const batchAnyDrive = targets.some((f) => f.drive_file_id)
        const lines = releaseConfirmLines({ count: cnt, provider: releaseProvider, anyDrive: batchAnyDrive, driveMirrorEnabled, driveMirrorFolder })
        const onGo = () => { setConfirm(null); if (isBatch) publishAll(targets.map((f) => f.file), confirm.folderName || ''); else publish(confirm.file) }
        return (
          <div role="dialog" aria-modal="true" aria-label="Confirm release" onClick={() => setConfirm(null)}
               style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.42)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 20 }}>
            <div onClick={(e) => e.stopPropagation()}
                 style={{ background: 'var(--panel, #fff)', color: 'var(--ink)', border: '1px solid var(--line)', borderRadius: 12, padding: '20px 22px', maxWidth: 520, width: '100%', boxShadow: '0 12px 40px rgba(0,0,0,0.25)' }}>
              <h3 style={{ margin: '0 0 12px' }}>{isBatch ? `Publish ${cnt} corrected ${cnt === 1 ? 'copy' : 'copies'}?` : `Release ${confirm.file}?`}</h3>
              <ul style={{ margin: '0 0 18px', paddingLeft: 18, fontSize: 13.5, lineHeight: 1.65 }}>
                {confirm.folderName && <li>Release folder: “{confirm.folderName}”</li>}
                {lines.map((l, i) => <li key={i}>{l}</li>)}
              </ul>
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button className="ghost" onClick={() => setConfirm(null)}>Cancel</button>
                <button className="qbtn approve" onClick={onGo} disabled={cnt === 0}>{isBatch ? `Publish ${cnt}` : 'Release'}</button>
              </div>
            </div>
          </div>
        )
      })()}
    </>
  )
}
