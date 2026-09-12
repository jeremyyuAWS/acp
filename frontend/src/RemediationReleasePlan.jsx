import { useEffect, useRef, useState } from 'react'
import { getAutomaticRelease } from './api.js'
import { releasePlanKey } from './releasePlanIntent.js'
import ReleaseDestinationPicker from './ReleaseDestinationPicker.jsx'
import InfoTip from './InfoTip.jsx'
import { readWithRetry } from './readWithRetry.js'
import './remediation-auto-release.css'

export default function RemediationReleasePlan({ scanId, files, intent, onChange, disabled = false, read = getAutomaticRelease, requireChoice = false, compact = false, onAnswered }) {
  const key = releasePlanKey(scanId, files)
  const [destination, setDestination] = useState(null)
  const [targetProvider, setTargetProvider] = useState(null)
  useEffect(() => { setDestination(null); setTargetProvider(null) }, [key])
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [reviewKey, setReviewKey] = useState(null)
  const choice = useRef({ key, review: false })
  if (choice.current.key !== key) choice.current = { key, review: false }
  const currentIntent = useRef(intent)
  currentIntent.current = intent
  const paused = useRef(disabled)
  paused.current = disabled
  useEffect(() => {
    let live = true, timer = null, cancelRead = null, refreshes = 0
    const started = Date.now()
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
      let planning
      try {
        const deadline = new Promise((resolve, reject) => {
          cancelRead = () => { controller.abort(); reject(new DOMException('Read cancelled', 'AbortError')) }
          timeout = window.setTimeout(() => {
            controller.abort()
            reject(new Error('Publishing readiness took too long to respond.'))
          }, 20000)
        })
        const result = await Promise.race([readWithRetry(() => read(scanId, files, { signal: controller.signal, destination }), { signal: controller.signal }), deadline])
        if (!live) return
        planning = { key, ...(result?.planning || { available: false, reason: 'Automatic publishing requires a connected destination.' }) }
        setPreview(planning); setError('')
        const next = planning.available ? { key, scanId, scope_files: [...files], files: [...planning.files], destination: { ...planning.destination }, source_revision: planning.source_revision, allow_remaining_issues: true, include_reports: true } : null
        const prior = currentIntent.current
        // A refreshed eligible subset or revision is a new draft, never expanded consent.
        if (background && prior?.key === key && JSON.stringify([prior.files, prior.destination, prior.source_revision]) !== JSON.stringify([next?.files, next?.destination, next?.source_revision])) {
          onChange(null); onAnswered?.(false)
        } else if (!requireChoice && next && !choice.current.review && !background) onChange(next)
      } catch (failure) {
        if (!live) return
        setError('The release destination could not be checked.')
        if (background && currentIntent.current?.key === key) { onChange(null); onAnswered?.(false) }
        if (![401, 403, 404].includes(failure?.status) && background) planning = { available: false }
      } finally {
        window.clearTimeout(timeout); cancelRead = null
      }
      schedule(planning)
    }
    refresh()
    return () => { live = false; window.clearTimeout(timer); cancelRead?.() }
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
    {error && <p role="alert">{error} <button className="linklike" type="button" disabled={disabled} onClick={() => setReload(n => n + 1)}>Refresh destination</button></p>}
  </section>
}
