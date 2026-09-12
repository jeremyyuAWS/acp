import BidirectionalKpiCounter from './BidirectionalKpiCounter.jsx'
import './workflow-outcome-tiles.css'

const valid = value => Number.isSafeInteger(value) && value >= 0
const FINDING = [
  ['queued', 'Queued', 'blue', ['awaiting_recorded_outcome', 'not_in_remediation_breakdown']],
  ['processing', 'Applying & checking', 'purple', ['approved_pending_verification', 'approved_awaiting_verification']],
  ['attention', 'Needs attention', 'pink', ['awaiting_review', 'unchanged_no_fix', 'failed']],
  ['verified', 'Verified fixes', 'green', ['resolved_verified']],
  ['excluded', 'Excluded', 'gray', ['excluded', 'superseded']],
]
const PUBLICATION = [
  ['queued', 'Queued', 'blue', ['waiting', 'queued']],
  ['processing', 'Publishing', 'purple', ['processing']],
  ['published', 'Published', 'green', ['published', 'completed_unverified']],
  ['attention', 'Delivery issues', 'pink', ['failed', 'cancelled']],
  ['skipped', 'Skipped', 'gray', ['skipped']],
]

// Group the recorded partition, never operational job totals or approval counts.
export function outcomeTileModel(stage, domain) {
  const configuration = stage === 'remediate' ? FINDING : stage === 'release' ? PUBLICATION : null
  if (!configuration || !domain?.buckets || domain.available === false) return null
  const buckets = domain.buckets
  const keys = Object.keys(buckets)
  const known = new Set(configuration.flatMap(item => item[3]))
  const balanced = valid(domain.total) && Object.values(buckets).every(valid)
    && Object.values(buckets).reduce((sum, value) => sum + value, 0) === domain.total
  return { balanced, total: domain.total, tiles: configuration.map(([key, label, tone, group]) => ({
    key, label, tone, value: balanced ? group.reduce((sum, name) => sum + (buckets[name] || 0), 0)
      + (key === 'attention' ? keys.filter(name => !known.has(name)).reduce((sum, name) => sum + buckets[name], 0) : 0) : null,
  })) }
}

export default function WorkflowOutcomeTiles({ stage, domain, baseline = null, executionId, onFilter, queueMode = false }) {
  const model = outcomeTileModel(stage, domain)
  if (!model) return null
  const beforeValues = baseline?.available === true && baseline.run_id === executionId
    ? (stage === 'remediate' ? baseline.findings : baseline.publication) : null
  const baselineBalanced = beforeValues && model.tiles.every(tile => valid(beforeValues[tile.key]))
    && model.tiles.reduce((sum, tile) => sum + beforeValues[tile.key], 0) === model.total
  const title = stage === 'remediate' ? 'Finding progress' : 'Publication progress'
  return <section className="workflow-outcome-tiles" aria-label={title}>
    <h4>{title}</h4>
    <p className="workflow-outcome-tiles__scope">{stage === 'remediate'
      ? `${model.total ?? '—'} assessed findings · this remediation run`
      : `${model.total ?? '—'} requested files · this release only`}</p>
    <div className="workflow-outcome-tiles__grid">
      {model.tiles.map((tile) => {
        const old = baselineBalanced ? beforeValues[tile.key] : null
        const delta = old != null && tile.value != null ? tile.value - old : null
        const content = <>
          <span className="workflow-outcome-tiles__label">{tile.label}</span>
          <strong aria-label={`${tile.label}: ${tile.value ?? 'unavailable'}`}><span className="workflow-outcome-tiles__now">Now</span>{tile.value == null ? '—' : <BidirectionalKpiCounter value={tile.value} />}</strong>
          <span className="workflow-outcome-tiles__before">{old == null ? 'Before unavailable' : `Before: ${old.toLocaleString()}`}</span>
          {delta != null && <span className="workflow-outcome-tiles__net">{delta > 0 ? '+' : delta < 0 ? '−' : ''}{Math.abs(delta).toLocaleString()} since starting</span>}
          <span className="workflow-outcome-tiles__fill" aria-hidden="true" style={{ transform: `scaleX(${model.total > 0 && tile.value != null ? tile.value / model.total : 0})` }} />
        </>
        const props = { className: `workflow-outcome-tiles__tile tone-${tile.tone} ${tile.key === 'verified' ? 'finding-outcome-kpis__verified' : ''}`, key: `${executionId}:${tile.key}` }
        return onFilter ? <button {...props} type="button" aria-haspopup={queueMode ? 'dialog' : undefined} onClick={() => onFilter(tile.key)}>{content}</button> : <div {...props}>{content}</div>
      })}
    </div>
    <p className="workflow-outcome-tiles__note">{!model.balanced ? 'Updating: outcome totals are being reconciled.' : stage === 'remediate'
      ? 'Approval starts work; only checked fixes count as verified. Excluded includes superseded records; see Outcome details.'
      : 'Published includes delivered copies with remaining issues. Publication does not certify accessibility; see Outcome details.'}</p>
  </section>
}
