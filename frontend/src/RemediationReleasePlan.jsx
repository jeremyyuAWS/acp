import { useEffect, useRef, useState } from 'react'
import { getAutomaticRelease } from './api.js'
import { releasePlanKey } from './releasePlanIntent.js'
import InfoTip from './InfoTip.jsx'
import './remediation-auto-release.css'

export default function RemediationReleasePlan({ scanId, files, intent, onChange, disabled = false, read = getAutomaticRelease, requireChoice = false, compact = false, onAnswered }) {
  const key = releasePlanKey(scanId, files)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [reviewKey, setReviewKey] = useState(null)
  const choice = useRef({ key, review: false })
  if (choice.current.key !== key) choice.current = { key, review: false }
  useEffect(() => {
    let live = true
    const controller = new AbortController()
    setPreview(null); setError(''); onChange(null); onAnswered?.(false)
    if (!scanId || !files.length) return () => { live = false; controller.abort() }
    read(scanId, files, { signal: controller.signal }).then(result => {
      if (!live) return
      const planning = { key, ...(result?.planning || { available: false, reason: 'Automatic publishing requires a connected destination.' }) }
      setPreview(planning)
      if (!requireChoice && planning.available && !choice.current.review) onChange({ key, scanId, files: [...planning.files], destination: { ...planning.destination }, source_revision: planning.source_revision, allow_remaining_issues: true, include_reports: true })
    }).catch(() => { if (live) setError('The release destination could not be checked.') })
    return () => { live = false; controller.abort() }
  }, [key, reload, read])
  const ready = preview?.key === key && preview.available === true
  const checked = ready && intent?.key === key
  const choose = review => {
    onAnswered?.(true)
    choice.current = { key, review }
    setReviewKey(review ? key : null)
    onChange(review ? null : { key, scanId, files: [...preview.files], destination: { ...preview.destination }, source_revision: preview.source_revision, allow_remaining_issues: true, include_reports: true })
  }
  return <section className="rem-auto-release" aria-label="Release option for this plan">
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><strong>{compact ? 'Auto-publish?' : 'When should files be published?'}</strong>
      {!compact && <InfoTip label="automatic release">Approve plan and start authorizes this run to publish saved copies after automatic processing, even when issues remain. Your selected rules and AI settings still apply. Human inspection is optional; unapproved suggestions are not applied. The scan summary and per-file checklist distinguish verified fixes, applied but unverified changes, remaining issues, and checks that could not run. Publishing does not certify accessibility. Permission lasts up to 24 hours. Changing the scope creates a new draft plan; permission begins only when that plan is accepted. Use Live to stop future releases. Original files stay unchanged.</InfoTip>}
    </div>
    <label className="rem-auto-release-option"><input type="radio" name={`release-mode-${scanId}`} checked={!!checked} disabled={disabled || !ready} onChange={() => choose(false)} /><strong>{compact ? 'Yes — publish processed copies and reports automatically' : 'Fix and publish automatically'}</strong></label>
    <label className="rem-auto-release-option"><input type="radio" name={`release-mode-${scanId}`} checked={reviewKey === key && choice.current.review} disabled={disabled} onChange={() => choose(true)} /><strong>{compact ? 'No — review in Release before publishing' : 'Review before publishing'}</strong></label>
    <p>Unapproved suggestions remain unapplied. Remaining issues are included in the follow-up checklist.</p>
    <p><b>Destination:</b> {preview?.destination_label ? `${preview.destination_label} / Remediated / Timestamp + user email` : (preview || error ? 'Not available' : 'Checking destination…')}</p>
    {preview?.reason && <p>{preview.reason}</p>}
    {preview?.blocked_files?.length > 0 && <ul aria-label="Files blocking automatic publishing">
      {preview.blocked_files.map(({file, reason}) => <li key={file}><b>{file}</b> — {reason}</li>)}
    </ul>}
    {preview && !ready && <p>You can still run remediation. Resolve the issue above, then <button type="button" className="linklike" disabled={disabled} onClick={() => setReload(n => n + 1)}>Refresh publishing readiness</button>.</p>}
    {error && <p role="alert">{error} <button className="linklike" type="button" disabled={disabled} onClick={() => setReload(n => n + 1)}>Refresh destination</button></p>}
  </section>
}
