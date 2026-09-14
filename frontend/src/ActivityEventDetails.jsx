import { useId, useRef, useState } from 'react'
import { activityEventSummary, activityEvidenceModel } from './activityEventDetails.js'
import './activity-event-details.css'

export default function ActivityEventDetails({ event = {}, loadEvidence, downloadSavedCopy, downloadEvidence }) {
  const summary = activityEventSummary(event)
  const identity = `${event.key || event.id || ''}:${event.snapshotSha256 || ''}`
  const current = useRef(identity)
  current.current = identity
  const [state, setState] = useState({identity, status:'idle', payload:null})
  const [downloadError, setDownloadError] = useState(null)
  const evidenceId = useId()
  const value = state.identity === identity ? state : {status:'idle', payload:null}
  const model = activityEvidenceModel(value.payload, event)
  if (!summary.visible) return null
  async function load() {
    if (!summary.bound || typeof loadEvidence !== 'function') {
      setState({identity, status:'unavailable', payload:null}); return
    }
    setState({identity, status:'loading', payload:null})
    try {
      const payload = await loadEvidence(event.id)
      if (current.current === identity) setState({identity, status:'ready', payload})
    } catch {
      if (current.current === identity) setState({identity, status:'unavailable', payload:null})
    }
  }
  async function download(action) {
    setDownloadError(null)
    try { await action(event.id) } catch (error) { if (current.current === identity) setDownloadError(error?.status === 409 ? 'This saved version is no longer available. No newer copy was substituted.' : 'The exact saved-version download could not be completed. Try again.') }
  }
  return <div className="activity-event-details">
    <p className="activity-event-details__summary"><strong>{summary.criteria.length ? summary.criteria.map(sc => `SC ${sc}`).join(' · ') : 'Criterion Not Recorded'}</strong><span>{summary.location || 'Location Unavailable'}</span></p>
    {summary.nextAction && <p className="activity-event-details__action"><strong>Next:</strong> {summary.nextAction}</p>}
    <details onToggle={e => { if (e.currentTarget.open && value.status === 'idle') load() }}>
      <summary>View Changes and Evidence</summary>
      {value.status === 'loading' ? <p role="status">Loading recorded evidence…</p> : value.status !== 'idle' && !model.available ? <><p>Evidence for this event’s saved version is unavailable. Earlier activity is retained; current document results are not substituted.</p>{value.status === 'unavailable' && summary.bound && typeof loadEvidence === 'function' && <button type="button" className="linklike" onClick={load}>Retry Evidence</button>}</>
        : model.available && <div id={evidenceId}>
          {model.changes.length ? model.changes.map((change, index) => <section className="activity-event-details__change" key={index} aria-label={`Recorded change ${index + 1}`}>
            <p><strong>{change.criterion ? `SC ${change.criterion}` : 'Criterion Not Recorded'}</strong> · {change.location || 'Location Unavailable'}</p>
            <dl><div><dt>Before</dt><dd>{change.before || 'Before Value Unavailable'}</dd></div><div><dt>After</dt><dd>{change.after || 'After Value Unavailable'}</dd></div></dl>
            {change.textTruncated && <p>Excerpt shown; the recorded text is longer.</p>}
            <small>{change.verified ? 'This change passed its recorded check for the saved version.' : 'A passing check for this change is not recorded.'}</small>
          </section>) : <p>No before-and-after change records are linked to this event.</p>}
          {model.changesTruncated && <p>Showing {model.changes.length} of {model.changeCount ?? 'the recorded'} changes.</p>}
          <p><strong>{model.verificationLabel}</strong></p>
          <div className="activity-event-details__links">
            {model.savedCopyAvailable && typeof downloadSavedCopy === 'function' && <button type="button" className="linklike" onClick={() => download(downloadSavedCopy)}>Download This Saved Copy</button>}
            {typeof downloadEvidence === 'function' && <button type="button" className="linklike" onClick={() => download(downloadEvidence)}>Download Verification Evidence</button>}
          </div>
          {!model.savedCopyAvailable && <p>The exact saved copy is unavailable; no newer copy is linked here.</p>}
          <details><summary>Saved Version</summary><code>{model.artifact}</code></details>
          {downloadError && <p role="alert">{downloadError}</p>}
        </div>}
    </details>
  </div>
}
