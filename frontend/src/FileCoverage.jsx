import BidirectionalKpiCounter from './BidirectionalKpiCounter.jsx'
import { fileCoverage, comparison } from './fileCoverageModel.js'

export function KpiComparison({ value, baseline }) {
  const saved = comparison(value, baseline)
  return <small className="kpi-comparison">{saved ? <>Before: {saved.before.toLocaleString()}<span>Since start: {saved.delta > 0 ? '+' : saved.delta < 0 ? '−' : ''}{Math.abs(saved.delta).toLocaleString()}</span></> : 'Before unavailable'}</small>
}

export default function FileCoverage({ evidence, animate = false, onSelect, selected, queueMode = false }) {
  const state = fileCoverage(evidence)
  const tiles = [['withFindings', 'Files with findings', 'attention'], ['processed', 'Files processed', 'verified'], ['remaining', 'Files still to process', 'processing']]
  return <section className="file-coverage" aria-label="File coverage"><h3>File coverage</h3>
    <div className="remediation-progress-summary-counts file-coverage-counts">{tiles.map(([key, label, color]) => {
      const fraction = state.withFindings > 0 && state[key] != null ? state[key] / state.withFindings : 0
      const content = <><span className="kpi-tile-fill" aria-hidden="true" style={{width:`${Math.min(100, fraction * 100)}%`}}/><span className="progress-tile-label">{label}</span><strong><BidirectionalKpiCounter value={state[key]} animate={animate}/></strong>
        {key === 'processed' && <small>{state.processed == null ? 'Processing coverage unavailable' : `${state.processed} of ${state.withFindings} files with findings`}</small>}
        <KpiComparison value={state[key]} baseline={evidence?.baseline?.[key]}/></>
      return onSelect ? <button type="button" className={`coverage-${color}`} key={key} title={key === 'processed' ? 'A remediation attempt finished; unresolved findings or failed fixes may remain.' : label} aria-pressed={queueMode ? undefined : selected === key} aria-expanded={queueMode ? selected === key : undefined} aria-haspopup={queueMode ? 'dialog' : undefined} onClick={() => onSelect(key)} aria-label={`${label}: ${state[key] ?? 'unavailable'}`}>{content}</button>
        : <div className={`coverage-${color}`} key={key}>{content}</div>
    })}</div><p className="muted">Processed means a remediation attempt finished. It does not mean fully remediated, verified, or published.</p>
    {!state.available && <p role="status">{state.unknown == null ? 'Recorded processing coverage is unavailable for this run.' : `Awaiting recorded processing outcomes for ${state.unknown} file${state.unknown === 1 ? '' : 's'}.`}</p>}
  </section>
}
