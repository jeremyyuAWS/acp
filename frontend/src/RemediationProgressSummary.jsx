import LiveCounter from './LiveCounter.jsx'
import './RemediationProgressSummary.css'

export const PROGRESS_STATES = [
  ['processing', 'Processing'], ['verified', 'Verified'], ['attention', 'Needs attention'],
  ['ready', 'Ready to publish'], ['published', 'Published'],
]

// Callers supply recorded document states. Unknown documents remain explicit;
// neither a corrected copy nor an AI approval proves verification or publication.
export default function RemediationProgressSummary({ documents = [], selected, onSelect, reconciling = false, animate = false }) {
  const known = new Set(PROGRESS_STATES.map(([key]) => key))
  const unknown = documents.filter(document => !known.has(document.progressState)).length
  const selectedLabel = PROGRESS_STATES.find(([key]) => key === selected)?.[1]
  const selectedCount = documents.filter(document => document.progressState === selected).length
  return <section className="remediation-progress-summary" aria-label="Document progress">
    <div className="remediation-progress-summary-heading"><h3>Document progress</h3>
      {onSelect && <button type="button" aria-pressed={!selected} onClick={() => onSelect(null)}>Show all {documents.length} document{documents.length === 1 ? '' : 's'}</button>}
    </div>
    {onSelect && <p className="remediation-progress-filter-help">Select a status to filter the document list below.</p>}
    <div className="remediation-progress-summary-counts">{PROGRESS_STATES.map(([key, label]) => {
      const count = documents.filter(document => document.progressState === key).length
      const content = <><strong>{animate ? <LiveCounter value={count} /> : count}</strong><span>{label}</span></>
      return onSelect ? <button type="button" key={key} className={`progress-${key}`} aria-label={`Show documents: ${label} (${count})`} aria-pressed={selected === key} onClick={() => onSelect(key)}>{content}<small>{selected === key ? 'Selected filter' : 'Filter document list'}</small></button>
        : <div key={key} className={`progress-${key}`}>{content}</div>
    })}</div>
    {onSelect && <p className="remediation-progress-filter-selection" role="status">{selectedLabel ? `Showing ${selectedLabel.toLowerCase()} documents: ${selectedCount} of ${documents.length}.` : `Showing all ${documents.length} document${documents.length === 1 ? '' : 's'}.`}</p>}
    {(reconciling || unknown > 0) && <p role="status">{unknown > 0 ? `${unknown} document${unknown === 1 ? '' : 's'} awaiting confirmed progress.` : 'Refreshing confirmed progress…'} Counts reflect saved results.</p>}
    <p className="muted">Document stages are separate from finding counts. Verified means repairs passed checks; ready to publish also requires release eligibility.</p>
  </section>
}
