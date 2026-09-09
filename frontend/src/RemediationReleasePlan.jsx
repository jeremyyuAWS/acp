import { useEffect, useState } from 'react'
import { getAutomaticRelease } from './api.js'
import { releasePlanKey } from './releasePlanIntent.js'
import InfoTip from './InfoTip.jsx'
import './remediation-auto-release.css'

export default function RemediationReleasePlan({ scanId, files, intent, onChange, disabled = false, read = getAutomaticRelease }) {
  const key = releasePlanKey(scanId, files)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let live = true
    const controller = new AbortController()
    setPreview(null); setError(''); onChange(null)
    if (!scanId || !files.length) return () => { live = false; controller.abort() }
    read(scanId, files, { signal: controller.signal }).then(result => {
      if (live) setPreview({ key, ...(result?.planning || { available: false, reason: 'Automatic release planning is unavailable on this server.' }) })
    }).catch(() => { if (live) setError('The release destination could not be checked.') })
    return () => { live = false; controller.abort() }
  }, [key, reload, read])
  const ready = preview?.key === key && preview.available === true
  const checked = ready && intent?.key === key
  return <section className="rem-auto-release" aria-label="Release option for this plan">
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><label className="rem-auto-release-option">
      <input type="checkbox" checked={!!checked} disabled={disabled || !ready}
        onChange={event => onChange(event.target.checked ? { key, scanId, files: [...preview.files], destination: { ...preview.destination }, source_revision: preview.source_revision } : null)} />
      <strong>Automatically release files when ready</strong>
    </label>
    <InfoTip label="automatic release">
      When you approve this plan and start, release each selected file after its required approvals and verification pass. Other files can keep processing.
      {' '}{checked ? `Selected for ${files.length} file${files.length === 1 ? '' : 's'} in this plan. Permission starts only after this run is accepted and lasts up to 24 hours.` : 'Off by default for each new plan. This choice is separate from AI approval and is not saved as a future default.'}
      {' '}Changing files or leaving this page clears this choice. After starting, use Live to see progress or stop future releases. Corrected copies go into a timestamped release subfolder; originals stay unchanged.
    </InfoTip></div>
    <p><b>Destination:</b> {preview?.destination_label ? `${preview.destination_label} / Remediated / Release date and time` : (preview || error ? 'Not available' : 'Checking destination…')}</p>
    {preview?.reason && <p>{preview.reason}</p>}
    {error && <p role="alert">{error} <button className="linklike" type="button" disabled={disabled} onClick={() => setReload(n => n + 1)}>Refresh destination</button></p>}
  </section>
}
