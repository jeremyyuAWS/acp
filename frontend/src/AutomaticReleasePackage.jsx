import { useState } from 'react'
import { downloadPreparedReleasePackage } from './api.js'

export default function AutomaticReleasePackage({ scanId, authorization, download }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const packageJob = authorization?.package
  if (!packageJob) return null
  const ready = packageJob.status === 'done'
  const failed = ['dead', 'cancelled'].includes(packageJob.status)
  return <section className="panel" aria-label="Automatic download package">
    <strong>{ready ? 'Corrected copies ready to download' : failed ? 'Download package needs attention' : 'Preparing corrected copies for download…'}</strong>
    <p>{ready ? 'Your package includes corrected copies, a delivery manifest, and follow-up reports. No inspection required.' : failed ? 'The package could not be prepared. Individual corrected copies and reports remain available in Release.' : 'The package continues in the background and remains available after you return.'}</p>
    {ready && <button type="button" className="primary" disabled={busy} onClick={async () => {
      setBusy(true); setError('')
      try { await (download || downloadPreparedReleasePackage)(scanId, packageJob.job_id) }
      catch (failure) { setError(failure?.message || 'The package could not be downloaded. Try again.') }
      finally { setBusy(false) }
    }}>{busy ? 'Downloading…' : 'Download corrected copies & reports'}</button>}
    {error && <p role="alert">{error}</p>}
  </section>
}
