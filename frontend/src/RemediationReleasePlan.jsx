import { useEffect, useRef, useState } from 'react'
import { getAutomaticRelease, repairAutomaticReleaseSourceIdentity } from './api.js'
import { authEpoch } from './apiIdentity.js'
import { releasePlanKey } from './releasePlanIntent.js'
import ReleaseDestinationPicker from './ReleaseDestinationPicker.jsx'
import InfoTip from './InfoTip.jsx'
import { readWithRetry } from './readWithRetry.js'
import './remediation-auto-release.css'

export default function RemediationReleasePlan({ scanId, files, intent, onChange, disabled = false, read = getAutomaticRelease, repair = (...args) => repairAutomaticReleaseSourceIdentity(...args), requireChoice = false, compact = false, onAnswered }) {
  const key = releasePlanKey(scanId, files)
  const [destination, setDestination] = useState(null)
  const [targetProvider, setTargetProvider] = useState(null)
  useEffect(() => { setDestination(null); setTargetProvider(null) }, [key])
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [repairError, setRepairError] = useState('')
  const [repairStatus, setRepairStatus] = useState(null)
  useEffect(() => setRepairError(''), [key])
  const [reload, setReload] = useState(0)
  const [reviewKey, setReviewKey] = useState(null)
  const choice = useRef({ key, review: false })
  if (choice.current.key !== key) choice.current = { key, review: false }
  const currentIntent = useRef(intent)
  currentIntent.current = intent
  const paused = useRef(disabled)
  const repairAttempts = useRef(new Set())
  const safeReconnectRetries = useRef(new Set())
  paused.current = disabled
  useEffect(() => {
    let live = true, timer = null, cancelRead = null, refreshes = 0
    const started = Date.now()
    const identity = authEpoch()
    setPreview(null); setError(''); onChange(null); onAnswered?.(choice.current.review)
    if (!scanId || !files.length) return () => { live = false }
    const schedule = planning => {
      if (!live || (!planning?.blocked_files?.length && planning?.available !== false)
          || refreshes >= 60 || Date.now() - started >= 300000) return
      timer = window.setTimeout(() => {
        if (Date.now() - started > 300000) return
        if (paused.current || document.visibilityState === 'hidden') schedule(planning)
        else { refreshes += 1; refresh(true) }
      }, 5000)
    }
    const refresh = async (background = false) => {
      const controller = new AbortController()
      let timeout
      let planning, repairing = false
      try {
        const bounded = async (operation, milliseconds, message) => {
          const deadline = new Promise((resolve, reject) => {
            cancelRead = () => { controller.abort(); reject(new DOMException('Read cancelled', 'AbortError')) }
            timeout = window.setTimeout(() => { controller.abort(); reject(new Error(message)) }, milliseconds)
          })
          try { return await Promise.race([operation(), deadline]) }
          finally { window.clearTimeout(timeout); cancelRead = null }
        }
        const readPreview = () => bounded(
          () => readWithRetry(() => read(scanId, files, { signal: controller.signal, destination }), { signal: controller.signal }),
          20000, 'Publishing readiness took too long to respond.')
        const recoverSource = async () => {
          let result = await readPreview()
          const recovery = result?.planning?.source_identity_repair
          if (live && authEpoch() === identity && !paused.current
              && recovery?.available === true && recovery.reason === 'missing_default_drive_identity'
              && Array.isArray(recovery.files) && recovery.files.some(file => files.includes(file))
              && !repairAttempts.current.has(key)) {
            // One attempt for this exact scope, including reconnects and manual refreshes.
            // Repairs do not answer the publishing question or expand accepted consent.
            repairAttempts.current.add(key)
            planning = { key, ...result.planning }
            setPreview(planning)
            setRepairStatus({ key, count: recovery.files.filter(file => files.includes(file)).length })
            repairing = true
            await bounded(() => repair(scanId, { signal: controller.signal }), 90000, 'Source identity recovery took too long to respond.')
            repairing = false
            if (!live || authEpoch() !== identity) return null
            result = await readPreview()
          }
          return result
        }
        const result = await recoverSource()
        if (!live || authEpoch() !== identity) return
        planning = { key, ...(result?.planning || { available: false, reason: 'Automatic publishing requires a connected destination.' }) }
        setPreview(planning); setError('')
        if (planning.available) setRepairError('')
        const next = planning.available ? { key, scanId, scope_files: [...files], files: [...planning.files], destination: { ...planning.destination }, source_revision: planning.source_revision, allow_remaining_issues: true, include_reports: true } : null
        const prior = currentIntent.current
        // A refreshed eligible subset or revision is a new draft, never expanded consent.
        if (background && prior?.key === key && JSON.stringify([prior.files, prior.destination, prior.source_revision]) !== JSON.stringify([next?.files, next?.destination, next?.source_revision])) {
          onChange(null); onAnswered?.(false)
        } else if (!requireChoice && next && !choice.current.review && !background) onChange(next)
      } catch (failure) {
        if (!live || authEpoch() !== identity) return
        if (repairing) {
          if (failure?.code === 'microsoft_connection_required' && failure.sourceIdentityRequestSent === false) safeReconnectRetries.current.add(key)
          setRepairError(sourceRepairNotice(failure))
        }
        else setError('The release destination could not be checked.')
        if (background && currentIntent.current?.key === key) { onChange(null); onAnswered?.(false) }
        // A failed first read needs the same bounded recovery as a blocked preview.
        // Access/scope denials are terminal; an uncertain write is never replayed here.
        if ([401, 403, 404].includes(failure?.status)) planning = null
        else if (background || failure instanceof TypeError || [408, 429, 502, 503, 504].includes(failure?.status)
              || failure?.message === 'Publishing readiness took too long to respond.') planning = { available: false }
      } finally {
        window.clearTimeout(timeout); cancelRead = null
        if (live) setRepairStatus(previous => previous?.key === key ? null : previous)
      }
      schedule(planning)
    }
    refresh()
    return () => { live = false; window.clearTimeout(timer); cancelRead?.(); setRepairStatus(previous => previous?.key === key ? null : previous) }
  }, [key, reload, read, JSON.stringify(destination)])
  const ready = preview?.key === key && preview.available === true && !error && (!targetProvider || preview.destination?.provider === targetProvider)
  const checked = ready && intent?.key === key
  const choose = review => {
    onAnswered?.(true)
    choice.current = { key, review }
    setReviewKey(review ? key : null)
    onChange(review ? null : { key, scanId, scope_files: [...files], files: [...preview.files], destination: { ...preview.destination }, source_revision: preview.source_revision, allow_remaining_issues: true, include_reports: true })
  }
  return <section className="rem-auto-release" aria-label="Release option for this plan">
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><strong>Automatically apply fixes and publish corrected copies?</strong>
      {!compact && <InfoTip label="automatic release">Approve plan and start authorizes this run to publish saved copies after automatic processing, even when issues remain. Your selected rules and AI settings still apply. Your acceptance authorizes available fixes and AI suggestions within the selected criteria. Changes are verified. Human inspection is optional. The scan summary and per-file checklist distinguish verified fixes, applied but unverified changes, remaining issues, and checks that could not run. Publishing does not certify accessibility. Permission lasts up to 24 hours. Changing the scope creates a new draft plan; permission begins only when that plan is accepted. Use Live to stop future releases. Original files stay unchanged.</InfoTip>}
    </div>
    <label className="rem-auto-release-option"><input type="radio" name={`release-mode-${scanId}`} checked={!!checked} disabled={disabled || !ready} onChange={() => choose(false)} /><strong>Yes — apply all available fixes and AI suggestions, then publish automatically</strong></label>
    <label className="rem-auto-release-option"><input type="radio" name={`release-mode-${scanId}`} checked={reviewKey === key && choice.current.review} disabled={disabled} onChange={() => choose(true)} /><strong>No — let me review and publish later</strong></label>
    <p>No individual approvals or inspection required. Available changes are checked automatically. Anything that cannot be fixed is included in the follow-up report. Original files stay unchanged.</p>
    <p><b>Destination:</b> {preview?.destination_label ? preview.destination?.provider === 'local' ? 'Download package · prepared automatically with corrected copies and follow-up reports' : `${preview.destination_label} / Remediated / Timestamp + user email` : (preview?.blocked_files?.length && !preview.available ? 'Waiting for assessment and source checks' : preview || error ? 'Not available' : 'Checking destination…')}</p>
    {repairStatus?.key === key && <p role="status" aria-live="polite">Checking source details for {repairStatus.count} {repairStatus.count === 1 ? 'file' : 'files'}… Your assessment is saved; no rescan is needed.</p>}
    {preview?.source === 'local' && !preview.destination_locked && <label>Publish to <select aria-label="Publishing destination" disabled={disabled} value={targetProvider || preview.destination?.provider || 'local'} onChange={event => {
      const provider = event.target.value
      setTargetProvider(provider); onChange(null); onAnswered?.(false); setReviewKey(null)
      setDestination(provider === 'local' ? { provider, folder_id: 'root', folder_name: 'Download package' } : provider === 'drive' ? { provider, folder_id: 'root', folder_name: 'Google Drive root' } : null)
    }}><option value="local">Download package</option><option value="drive">Google Drive</option><option value="sharepoint">SharePoint / OneDrive</option></select></label>}
    {!preview?.destination_locked && ['drive', 'sharepoint'].includes(targetProvider || preview?.destination?.provider) && <ReleaseDestinationPicker provider={targetProvider || preview.destination.provider} value={destination || (preview.destination?.provider === (targetProvider || preview.destination.provider) ? preview.destination : null)} onChange={value => { setDestination(value); onChange(null); onAnswered?.(false) }} onError={failure => setError(failure?.message || 'The destination could not be saved.')} />}
    {targetProvider === 'sharepoint' && preview?.destination?.provider !== 'sharepoint' && <p>Choose a Microsoft folder to publish uploaded files.</p>}
    {preview?.reason && <p>{preview.reason}</p>}
    {preview?.blocked_files?.length > 0 && <details><summary>Show publishing requirements</summary><ul aria-label="Files blocking automatic publishing">
      {preview.blocked_files.map(({file, reason}) => <li key={file}><b>{file}</b> — {reason}</li>)}
    </ul></details>}
    {preview && (!ready || preview.blocked_files?.length > 0) && <p>Publishing readiness refreshes automatically for up to five minutes while this page is open. You can still run remediation. Resolve the issue above, then <button type="button" className="linklike" disabled={disabled} onClick={() => setReload(n => n + 1)}>Refresh publishing readiness</button>.</p>}
    {repairError && <p role="alert">{repairError}{safeReconnectRetries.current.has(key) && <> <button type="button" className="linklike" disabled={disabled} onClick={() => {
      // Only a known credential failure before dispatch is safe to try again.
      // A timed-out or otherwise uncertain POST retains its one-attempt guard.
      safeReconnectRetries.current.delete(key); repairAttempts.current.delete(key); setRepairError(''); setReload(n => n + 1)
    }}>Retry source checks after reconnecting</button></>}</p>}
    {error && <p role="alert">{error} <button className="linklike" type="button" disabled={disabled} onClick={() => setReload(n => n + 1)}>Refresh destination</button></p>}
  </section>
}

function sourceRepairNotice(failure) {
  if (failure?.code === 'microsoft_connection_required' && failure.sourceIdentityRequestSent === false) return 'Reconnect Microsoft in Sources, then retry source checks here. Your assessment is saved; no rescan is needed. No source-recovery request was sent.'
  const reason = failure?.detail?.reason
  if (failure?.detail?.code === 'source_identity_repair_blocked') {
    if (reason === 'microsoft_connection_required') return 'Reconnect SharePoint to confirm source access. No files were published.'
    if (['source_changed', 'assessment_source_mismatch', 'source_drive_mismatch', 'source_identity_mismatch'].includes(reason)) return 'The source files changed or no longer match this assessment. Assess them again before automatic publishing.'
    if (reason === 'provider_metadata_unavailable') return 'SharePoint source details are temporarily unavailable. Publishing readiness will refresh automatically.'
    if (reason === 'provider_metadata_timeout') return 'SharePoint source checks were interrupted. Readiness will refresh automatically; source recovery will not be repeated.'
    if (reason === 'assessment_incomplete') return 'Assessment must finish before source details can be confirmed.'
    return 'Source details could not be safely confirmed. Assess the selected files again before automatic publishing.'
  }
  if (failure?.message === 'Source identity recovery took too long to respond.') return 'Source checks are taking longer than expected. Readiness will refresh automatically; source recovery will not be repeated.'
  if (failure instanceof TypeError) return 'Source recovery could not be confirmed after a connection interruption. Readiness will refresh automatically; the recovery request will not be repeated.'
  return 'Reconnect SharePoint to confirm source access. No files were published.'
}
