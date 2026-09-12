import './RemediationProgressSummary.css'

export const PROGRESS_STATES = [
  ['processing', 'Processing'], ['verified', 'Verified'], ['attention', 'Needs attention'],
  ['ready', 'Ready to publish'], ['published', 'Published'],
]

// Callers supply recorded document states. Unknown documents remain explicit;
// neither a corrected copy nor an AI approval proves verification or publication.
export default function RemediationProgressSummary({ documents = [], selected, onSelect, reconciling = false }) {
  const known = new Set(PROGRESS_STATES.map(([key]) => key))
  const unknown = documents.filter(document => !known.has(document.progressState)).length
  return <section className="remediation-progress-summary" aria-label="Document progress">
    <div className="remediation-progress-summary-heading"><h3>Document progress</h3>
      {onSelect && <button type="button" aria-pressed={!selected} onClick={() => onSelect(null)}>All {documents.length}</button>}
    </div>
    <div className="remediation-progress-summary-counts">{PROGRESS_STATES.map(([key, label]) => {
      const count = documents.filter(document => document.progressState === key).length
      const content = <><strong>{count}</strong><span>{label}</span></>
      return onSelect ? <button type="button" key={key} className={`progress-${key}`} aria-pressed={selected === key} onClick={() => onSelect(key)}>{content}</button>
        : <div key={key} className={`progress-${key}`}>{content}</div>
    })}</div>
    {(reconciling || unknown > 0) && <p role="status">{unknown > 0 ? `${unknown} document${unknown === 1 ? '' : 's'} awaiting confirmed progress.` : 'Refreshing confirmed progress…'} Counts reflect saved results.</p>}
    <p className="muted">Document stages are separate from finding counts. Verified means repairs passed checks; ready to publish also requires release eligibility.</p>
  </section>
}
