import { useEffect, useId, useRef, useState } from 'react'
import { planReleaseContinuation, authorizeReleaseContinuation, getReleaseContinuation, resumeReleaseContinuation } from './api.js'
import './release-quick-actions.css'

export default function ReleaseQuickActions({ runId, files = [], ready = [], destination, folderName = '', destinationLabel,
  announcement, destinationPicker, destinationContent, destinationLocked = false, destinationPending = false, readOnly, publishing, releaseOptions, allowRemainingIssues = false, readyReasons = [], fileStates = {}, publishedFolders = [], providerLabel = 'the destination', onReady, onProgress }) {
  const reasonId = useId()
  const [excluded, setExcluded] = useState(new Set())
  useEffect(() => { setExcluded(new Set()) }, [runId])
  const selectedReady = ready.filter(file => !excluded.has(file.file))
  const readyNames = new Set(ready.map(file => file.file))
  const deliveredCount = files.filter(file => fileStates[file.file]?.status === 'released').length
  const allDelivered = files.length > 0 && deliveredCount === files.length
  const folderLinks = publishedFolders.filter(folder => folder.url)
  const [plan, setPlan] = useState(null)
  const [active, setActive] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const lock = useRef(false)
  const progressRef = useRef(onProgress)
  progressRef.current = onProgress
  const key = JSON.stringify([runId, files.map(f => [f.file, f.corrected_sha256, f.remediated_at]), destination, folderName])
  const currentKey = useRef(key)
  currentKey.current = key
  useEffect(() => {
    let live = true, settled = false
    const controller = new AbortController()
    setPlan(null); setError('')
    setChecking(Boolean(runId && files.length && !readOnly))
    if (!runId || !files.length || readOnly) return
    const deadline = setTimeout(() => {
      if (!live || settled) return
      settled = true; controller.abort(); setChecking(false)
      setError('Eligibility could not be confirmed in time. Refresh to try again. Ready files can still be published.')
    }, 20000)
    const load = async () => {
      try {
        const result = await planReleaseContinuation(runId, files.map(f => f.file), destination, folderName, { signal: controller.signal })
        if (!result?.id || !result?.intent) throw new Error('Eligibility could not be confirmed. Refresh before authorizing changes.')
        if (live && !settled) setPlan({ ...result, key })
      } catch (e) { if (live && !settled) setError(e?.message || 'Eligible changes could not be checked. Ready files can still be published.') }
      finally {
        clearTimeout(deadline)
        if (live && !settled) { settled = true; setChecking(false) }
      }
    }
    load()
    return () => { live = false; clearTimeout(deadline); controller.abort() }
  }, [key, refresh, readOnly])
  useEffect(() => {
    let live = true, timer
    setActive(null)
    if (!runId || readOnly) return
    const poll = async () => {
      try {
        const result = await getReleaseContinuation(runId)
        if (!live) return
        if (result && (!result.id || !result.intent)) throw new Error('Release status is incomplete')
        setActive(result)
        if (result) progressRef.current?.(result)
      } catch { /* Keep the last durable state while reconnecting. */ }
      if (live) timer = setTimeout(poll, 4000)
    }
    poll()
    return () => { live = false; clearTimeout(timer) }
  }, [runId, refresh, readOnly])
  const entries = Object.entries(plan?.intent?.files || {})
  const eligible = entries.reduce((n, [, f]) => n + (f.rows || []).filter(r => r.authorize).reduce((sum, r) => sum + r.proposals.length, 0), 0)
  const eligibleFiles = entries.filter(([, f]) => (f.rows || []).some(r => r.authorize)).length
  const activeRunning = active && ['waiting', 'publishing'].includes(active.status)
  async function approve() {
    if (lock.current || readOnly || !eligible || !plan || plan.key !== currentKey.current || activeRunning) return
    lock.current = true; setBusy(true); setError('')
    const frozen = plan
    try {
      const result = await authorizeReleaseContinuation(runId, frozen.id)
      if (!result?.id || !result?.intent) throw new Error('Authorization status is incomplete. Refresh status before retrying.')
      if (currentKey.current === frozen.key) { setActive(result); setRefresh(n => n + 1) }
    } catch (e) {
      setError(e?.message || 'Authorization was not confirmed. Refresh status before retrying.')
      if (e?.status === 409) setPlan(null)
    } finally { lock.current = false; setBusy(false) }
  }
  async function retry() {
    if (lock.current || readOnly || !active) return
    lock.current = true; setBusy(true)
    try { setActive(await resumeReleaseContinuation(runId, active.id)); setRefresh(n => n + 1) }
    catch (e) { setError(e?.message || 'The same authorized delivery could not be resumed.') }
    finally { lock.current = false; setBusy(false) }
  }
  const readyReason = readOnly ? 'History is read-only. Switch to the latest scan to publish.'
    : destinationPending ? 'Loading the saved release destination…' : publishing ? 'Publishing is in progress.' : !runId ? 'Choose a scan before releasing files.'
    : !files.length ? 'No files are selected in this scope.'
    : !ready.length ? 'No files are currently eligible for publishing.'
    : !selectedReady.length ? 'Select at least one ready file above.' : ''
  const approveReason = readOnly ? 'History is read-only. Switch to the latest scan to approve changes.'
    : destinationPending ? 'Loading the saved release destination…' : busy ? 'Authorization is in progress.' : activeRunning ? 'An authorized batch is already applying, verifying, and publishing. Follow its progress below.'
    : !runId ? 'Choose a scan before approving changes.' : !files.length ? 'No files are selected in this scope.'
    : checking ? 'Checking which proposals can be approved and published.'
    : !plan || plan.key !== key ? 'Eligibility is not confirmed. Refresh eligibility before approving changes.'
    : !eligible ? 'No complete, versioned proposals are ready for this action. See remaining requirements below.' : ''
  const outcomes = Object.entries(active?.progress || {}).filter(([file]) => file !== '_deadline')
  const count = state => outcomes.filter(([, result]) => result.state === state).length
  return <section className="panel release-quick" aria-label="Publish ready files and approved changes">
    <h3 className="release-quick-title">{allDelivered ? 'Publishing complete' : 'Publish your documents'}</h3>
    {deliveredCount > 0 && <div className="release-published-message" role="status">
      <strong>{allDelivered ? 'All files are already published.' : `${deliveredCount} ${deliveredCount === 1 ? 'file is' : 'files are'} already published.`}</strong>
      <p>{allDelivered ? 'There is nothing more to select for this release.' : 'Published files are greyed out below.'} Open the saved copies in {providerLabel}. Originals are unchanged.</p>
      {folderLinks.map((folder, index) => <a key={folder.id || folder.url} href={folder.url} target="_blank" rel="noopener noreferrer">Open published folder{folderLinks.length > 1 ? ` ${index + 1}` : ''} in {providerLabel} ↗</a>)}
      {!folderLinks.length && <p>The folder link is not available yet. Check the delivery receipt below for recorded file links.</p>}
    </div>}
    <section className="release-quick-step" aria-labelledby={`${reasonId}-files`}>
      <h4 id={`${reasonId}-files`}><span className="release-step-number">1</span> {allDelivered ? 'Published files' : 'Choose files'}</h4>
      {!allDelivered && releaseOptions}
      <div className="release-quick-summary"><strong>{allDelivered ? `${deliveredCount} delivered` : `${selectedReady.length} ready to publish`}</strong><span>{files.length} files in this scope</span></div>
      <div className="release-quick-file-list" aria-label="Files to publish">
        {files.map(file => <label key={file.file} className={`release-quick-file${fileStates[file.file]?.status === 'released' ? ' release-quick-file--delivered' : ''}`}>
          <input type="checkbox" aria-label={`Publish ${file.file}`} checked={readyNames.has(file.file) && !excluded.has(file.file)} disabled={readOnly || publishing || !readyNames.has(file.file)}
            onChange={event => setExcluded(previous => { const next = new Set(previous); event.target.checked ? next.delete(file.file) : next.add(file.file); return next })} />
          <span>{file.file}</span><small>{readyNames.has(file.file) ? 'Ready to publish' : fileStates[file.file]?.label || 'Not available for a new publish'}</small>
          {!readyNames.has(file.file) && fileStates[file.file]?.reason && <span className="release-quick-file-reason">{fileStates[file.file].reason}</span>}
        </label>)}
        {!files.length && <p>No files are selected in this scope.</p>}
      </div>
    </section>
    <section className="release-quick-step" aria-labelledby={`${reasonId}-destination`}>
      <h4 id={`${reasonId}-destination`}><span className="release-step-number">2</span> {allDelivered ? 'Published folder' : 'Confirm destination'}</h4>
      {destinationContent || <p><b>Destination:</b> {plan?.intent?.destination?.folder_name ? `${plan.intent.destination.folder_name} / Remediated / ${plan.intent.release_folder_name || folderName || 'Timestamp + user email'}` : destinationLabel}. Originals stay unchanged.</p>}
      {destinationLocked && <p className="muted">This release has started. Further copies and retries use this saved destination.</p>}
      {!readOnly && !destinationLocked && <details><summary>Change destination</summary>{destinationPicker}</details>}
    </section>
    <section className="release-quick-step" aria-labelledby={`${reasonId}-publish`}>
      <h4 id={`${reasonId}-publish`}><span className="release-step-number">3</span> {allDelivered ? 'Publication complete' : 'Publish copies'}</h4>
      <p>Saved copies are published with a scan summary and a per-file checklist of remaining work. Publishing does not certify accessibility.</p>
      <div className="release-quick-buttons">
      <div className="release-quick-action">
        <button disabled={allDelivered || Boolean(readyReason)} aria-describedby={!allDelivered && readyReason ? `${reasonId}-ready` : undefined} onClick={() => onReady(selectedReady.map(f => f.file))}>
          {allDelivered ? 'All files published ✓' : publishing ? 'Publishing copies…' : allowRemainingIssues ? `Publish saved copies (${selectedReady.length})` : `Publish ready files (${selectedReady.length})`}
        </button>
        {announcement && <p role="status">{announcement}</p>}
        {!allDelivered && readyReason && <div id={`${reasonId}-ready`}><p>{readyReason}</p>
          {!readOnly && !ready.length && readyReasons.slice(0, 3).map(reason => <p key={reason}>{reason}</p>)}
        </div>}
      </div>
      </div>
    </section>
    <details className="release-quick-proposals"><summary>Optional: apply more proposed changes before publishing</summary>
      <p>This separate action applies eligible proposals across the full scope shown above. Your saved-copy selection does not change this proposal batch.</p>
      <div className="release-quick-action">
        <button disabled={Boolean(approveReason)} aria-describedby={approveReason ? `${reasonId}-approve` : undefined} onClick={approve}>
          {busy ? 'Authorizing…' : 'Approve eligible changes and publish when ready'}
        </button>
        {approveReason && <p id={`${reasonId}-approve`}>{approveReason}</p>}
      </div>
    {checking && <p role="status">Checking which proposals can be approved and published… Ready files can still be published while this check runs.</p>}
    {eligible > 0 && <p>{eligible} proposed {eligible === 1 ? 'change' : 'changes'} across {eligibleFiles} {eligibleFiles === 1 ? 'file' : 'files'}. This action authorizes the current proposals, applies them, verifies the result, and publishes qualifying files to the destination above. Individual inspection is optional.</p>}
    {!eligible && plan && !activeRunning && <p>{ready.length ? 'Other files do not hold eligible proposals for this action.' : 'No eligible proposals can be applied automatically yet.'} Manual work and verification blockers remain separate.</p>}
    {entries.length > 0 && <details><summary>Inspect proposed changes and remaining blockers</summary>
      {entries.map(([file, data]) => <div key={file}><b>{file}</b>
        {(data.rows || []).filter(r => r.authorize).map(r => <details key={r.id}><summary>{r.rule_id} · {r.proposals.length} proposed changes</summary>
          {r.proposals.map((p, i) => <p key={i}>{p.proposed_value}</p>)}</details>)}
        {(data.blockers || []).map(reason => <p key={reason}>{reason}</p>)}
      </div>)}
    </details>}
    </details>
    {active && <div role="status" aria-label="Authorized Release progress">
      <b>{count('published')} delivered · {count('applying') + count('ready') + count('publishing')} in progress · {count('blocked') + count('failed') + count('needs_confirmation')} need attention</b>
      <p>{activeRunning ? 'Progress is saved. You can leave and return while approved changes are applied and verified.' : 'This authorized batch has finished. Files needing attention were not published.'}</p>
      <p>Authorized destination: {active.intent.destination?.folder_name || 'Source location'} / Remediated / {active.intent.release_folder_name || 'Timestamp + user email'}</p>
      <details><summary>Delivery results and remaining work</summary>{outcomes.map(([file, result]) => <p key={file}><b>{file}</b>: {result.message}
        {result.receipt?.published_url && <> · <a href={result.receipt.published_url} target="_blank" rel="noopener noreferrer">Open delivered copy</a></>}</p>)}</details>
      {count('failed') > 0 && <button className="ghost" disabled={busy || readOnly || activeRunning} onClick={retry}>Retry failed delivery with the same authorization</button>}
    </div>}
    {error && <p role="alert">{error} <button className="linklike" onClick={() => setRefresh(n => n + 1)}>Refresh eligibility and status</button></p>}
  </section>
}
