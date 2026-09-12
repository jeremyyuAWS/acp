import BidirectionalKpiCounter from './BidirectionalKpiCounter.jsx'
import FileCoverage, { KpiComparison } from './FileCoverage.jsx'
import './RemediationProgressSummary.css'

export const PROGRESS_STATES = [
  ['processing', 'Processing'], ['verified', 'Verified'], ['attention', 'Needs attention'],
  ['ready', 'Ready to publish'], ['published', 'Published'],
]

// Callers supply recorded document states. Unknown documents remain explicit;
// neither a corrected copy nor an AI approval proves verification or publication.
export default function RemediationProgressSummary({ documents = [], selected, onSelect, reconciling = false, animate = false, coverage, onCoverageSelect, selectedCoverage, baselineDocumentCounts, startedAt, queueMode = false, variant }) {
  const states = variant === 'release' ? PROGRESS_STATES.filter(([key]) => key !== 'attention') : PROGRESS_STATES
  const known = new Set(PROGRESS_STATES.map(([key]) => key))
  const unknown = documents.filter(document => !known.has(document.progressState)).length
  const selectedLabel = PROGRESS_STATES.find(([key]) => key === selected)?.[1]
  const selectedCount = documents.filter(document => document.progressState === selected).length
  return <section className="remediation-progress-summary" aria-label="Document progress">
    {startedAt && Number.isFinite(new Date(startedAt).getTime()) && <p className="muted">Before remediation → Live progress · Started {new Date(startedAt).toLocaleString()}</p>}
    {coverage && <FileCoverage evidence={coverage} animate={animate} onSelect={onCoverageSelect} selected={selectedCoverage} queueMode={queueMode}/> }
    <div className="remediation-progress-summary-heading"><h3>Document progress</h3>
      {onSelect && <button type="button" aria-pressed={queueMode ? undefined : !selected} aria-expanded={queueMode ? selected === null : undefined} aria-haspopup={queueMode ? 'dialog' : undefined} onClick={() => onSelect(null)}>Show all {documents.length} document{documents.length === 1 ? '' : 's'}</button>}
    </div>
    {onSelect && <p className="remediation-progress-filter-help">{queueMode ? 'Select a tile to open its file queue.' : 'Select a status to filter the document list below.'}</p>}
    <div className={`remediation-progress-summary-counts ${variant === 'release' ? 'remediation-progress-summary-counts--release' : ''}`}>{states.map(([key, label]) => {
      const count = documents.filter(document => document.progressState === key).length
      const fraction = documents.length ? count / documents.length : 0
      const content = <><span className="kpi-tile-fill" aria-hidden="true" style={{width:`${fraction * 100}%`}}/><span className="progress-tile-label">{label}</span><strong>{animate ? <BidirectionalKpiCounter value={count} /> : count}</strong><KpiComparison value={count} baseline={baselineDocumentCounts?.[key]}/></>
      return onSelect ? <button type="button" key={key} className={`progress-${key}`} aria-label={`Show documents: ${label} (${count})`} aria-pressed={queueMode ? undefined : selected === key} aria-expanded={queueMode ? selected === key : undefined} aria-haspopup={queueMode ? 'dialog' : undefined} onClick={() => onSelect(key)}>{content}<small>{queueMode ? 'Open file queue' : selected === key ? 'Selected filter' : 'Filter document list'}</small></button>
        : <div key={key} className={`progress-${key}`}>{content}</div>
    })}</div>
    {onSelect && !queueMode && <p className="remediation-progress-filter-selection" role="status">{selectedLabel ? `Showing ${selectedLabel.toLowerCase()} documents: ${selectedCount} of ${documents.length}.` : `Showing all ${documents.length} document${documents.length === 1 ? '' : 's'}.`}</p>}
    {(reconciling || unknown > 0) && <p role="status">{unknown > 0 ? `${unknown} document${unknown === 1 ? '' : 's'} awaiting confirmed progress.` : 'Refreshing confirmed progress…'} Counts reflect saved results.</p>}
    <p className="muted">Document stages are separate from finding counts. Verified means repairs passed checks; ready to publish also requires release eligibility.</p>
  </section>
}
