import InfoTip from './InfoTip.jsx'
import './file-coverage.css'
import BidirectionalKpiCounter from './BidirectionalKpiCounter.jsx'
import { fileCoverage, comparison } from './fileCoverageModel.js'

export function KpiComparison({ value, baseline }) {
  const saved = comparison(value, baseline)
  return <small className="kpi-comparison">{saved ? <>Before: {saved.before.toLocaleString()}<span>Since start: {saved.delta > 0 ? '+' : saved.delta < 0 ? '−' : ''}{Math.abs(saved.delta).toLocaleString()}</span></> : 'Before unavailable'}</small>
}

export default function FileCoverage({ evidence, animate = false, onSelect, selected, queueMode = false, compact = true }) {
  const state = fileCoverage(evidence)
  if (compact) {
    const metrics = [
      ['withFindings', 'Files with findings', 'Fixed repair scope', 'Selected documents with findings in this remediation run; this is not a count of repaired files.', 'neutral'],
      ['processed', 'Processing attempts finished', 'Automatic attempt finished', 'An attempt ended, including unsuccessful or skipped work. Remaining findings may still need attention.', 'increase'],
      ['remaining', 'Attempts not finished', 'No finished attempt recorded', 'May include waiting and in-progress files. These files are not necessarily all queued.', 'decrease'],
    ]
    return <section className="file-coverage file-coverage--compact" aria-label="File processing">
      <h3>File processing</h3>
      <div className="file-coverage-compact-counts">{metrics.map(([key, label, definition, detail, direction]) => {
        const Tag = onSelect ? 'button' : 'div'
        return <div className={`file-coverage-cell coverage-${key} coverage-${key === 'processed' ? 'verified' : key === 'remaining' ? 'processing' : 'attention'}`} key={key}>
          <Tag className="file-coverage-metric" type={onSelect ? 'button' : undefined} onClick={onSelect ? () => onSelect(key) : undefined}
            aria-pressed={onSelect && !queueMode ? selected === key : undefined} aria-expanded={onSelect && queueMode ? selected === key : undefined} aria-haspopup={onSelect && queueMode ? 'dialog' : undefined}>
            <span>{label}</span><strong aria-label={`${label}: ${state[key] ?? 'unavailable'}`}><BidirectionalKpiCounter value={state[key]} animate={animate} positiveDirection={direction}/></strong>
            <small>{definition}</small>{key !== 'withFindings' && comparison(state[key], evidence?.baseline?.[key]) && <KpiComparison value={state[key]} baseline={evidence.baseline[key]}/>}</Tag>
          <InfoTip label={label}>{detail}</InfoTip>
        </div>
      })}</div>
      {state.available && <>
        <progress className="file-coverage-bar" max={state.withFindings || 1} value={state.processed} aria-label="Processing attempts finished"/>
        <p className="file-coverage-copy">{state.processed.toLocaleString()} of {state.withFindings.toLocaleString()} files with findings have finished an automatic processing attempt. {state.remaining.toLocaleString()} have not finished an attempt.</p>
      </>}
      <p className="file-coverage-copy">A finished attempt may still leave unresolved findings. It does not mean fully remediated, verified, or published.</p>
      {!state.available && <p role="status">{state.unknown == null ? 'Recorded processing coverage is unavailable for this run.' : `Awaiting recorded processing outcomes for ${state.unknown} file${state.unknown === 1 ? '' : 's'}.`}</p>}
    </section>
  }
  const tiles = [['withFindings', 'Files with findings', 'attention', 'neutral'], ['processed', 'Files processed', 'verified', 'increase'], ['remaining', 'Files still to process', 'processing', 'decrease']]
  return <section className="file-coverage" aria-label="File coverage"><h3>File coverage</h3>
    <div className="remediation-progress-summary-counts file-coverage-counts">{tiles.map(([key, label, color, positiveDirection]) => {
      const fraction = state.withFindings > 0 && state[key] != null ? state[key] / state.withFindings : 0
      const content = <><span className="kpi-tile-fill" aria-hidden="true" style={{width:`${Math.min(100, fraction * 100)}%`}}/><span className="progress-tile-label">{label}</span><strong><BidirectionalKpiCounter value={state[key]} animate={animate} positiveDirection={positiveDirection}/></strong>
        {key === 'processed' && <small>{state.processed == null ? 'Processing coverage unavailable' : `${state.processed} of ${state.withFindings} files with findings`}</small>}
        {!(key === 'withFindings' && evidence?.population_fixed === true) && <KpiComparison value={state[key]} baseline={evidence?.baseline?.[key]}/>}</>
      return onSelect ? <button type="button" className={`coverage-${color}`} key={key} title={key === 'processed' ? 'A remediation attempt finished; unresolved findings or failed fixes may remain.' : label} aria-pressed={queueMode ? undefined : selected === key} aria-expanded={queueMode ? selected === key : undefined} aria-haspopup={queueMode ? 'dialog' : undefined} onClick={() => onSelect(key)} aria-label={`${label}: ${state[key] ?? 'unavailable'}`}>{content}</button>
        : <div className={`coverage-${color}`} key={key}>{content}</div>
    })}</div><p className="muted">Processed means a remediation attempt finished. It does not mean fully remediated, verified, or published.</p>
    {!state.available && <p role="status">{state.unknown == null ? 'Recorded processing coverage is unavailable for this run.' : `Awaiting recorded processing outcomes for ${state.unknown} file${state.unknown === 1 ? '' : 's'}.`}</p>}
  </section>
}
