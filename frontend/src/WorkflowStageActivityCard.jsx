import LiveHeartbeatBars from './LiveHeartbeatBars.jsx'
import { canonicalStageCardModel } from './canonicalStageCard.js'

const terminal = (state) => ['processing_complete', 'succeeded', 'failed', 'cancelled', 'superseded', 'integrity_failed'].includes(state)
const shown = (value) => value == null ? '—' : Number(value).toLocaleString()

export default function WorkflowStageActivityCard({ snapshot, receivedAt, onOpen }) {
  const model = canonicalStageCardModel(snapshot)
  if (!model) return null
  const domain = model.domain
  const done = domain?.accounted ?? model.accounted
  const total = domain?.total ?? model.total
  const pct = typeof done === 'number' && typeof total === 'number' && total > 0
    ? Math.max(0, Math.min(100, Math.round(done / total * 100))) : 0
  const findingAccounting = model.stage === 'remediate' && !!domain
  const missingOutcomes = findingAccounting && Number.isSafeInteger(total) && Number.isSafeInteger(done) && total > done ? total - done : 0
  const live = !terminal(snapshot.state)
  return <section className={`workflow-sse-card stage-${model.stage}`} aria-label={`${model.stageLabel} activity`}>
    <header className="workflow-sse-card__header">
      <div><strong>{model.stageLabel} · {model.stateLabel}</strong>
        <span>Workflow revision {model.workflowRevision ?? '—'}</span></div>
      {live && <LiveHeartbeatBars measuredAt={receivedAt} stage={model.stage}
        historyKey={`${snapshot.workflow_id || 'workflow'}:${model.executionId || model.stage}`} showText />}
      {onOpen && <button type="button" className="linklike" onClick={onOpen}>Open details →</button>}
    </header>
    <p className="workflow-sse-card__outcome"><b>{shown(done)} of {shown(total)}</b> {domain?.unit || model.unit}{findingAccounting ? ' accounted for' : ''}</p>
    <div className="workflow-sse-card__track" aria-label={`${pct}% ${findingAccounting ? 'accounted for' : 'complete'}`} role="progressbar"
      aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct}><span style={{ width: `${pct}%` }} /></div>
    {domain?.buckets?.length > 0 && <dl className="workflow-sse-card__metrics">
      {domain.buckets.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{shown(value)}</dd></div>)}
    </dl>}
    {findingAccounting && missingOutcomes > 0 && <p className="workflow-sse-card__notice">
      {shown(done)} with recorded outcomes + {shown(missingOutcomes)} awaiting an outcome = {shown(total)} assessed findings.
    </p>}
    {snapshot.omitted_assessment_groups?.length > 0 && <details>
      <summary>Findings not in the remediation breakdown — by file and SC</summary>
      <ul>{snapshot.omitted_assessment_groups.map(({ file, sc, count }) => <li key={`${file}:${sc}`}>
        <b>{file}</b> · SC {sc || 'not recorded'} · {shown(count)} {count === 1 ? 'finding' : 'findings'}
      </li>)}</ul>
    </details>}
    {!model.integrityOk && <p className="workflow-sse-card__notice"><b>Accounting is reconciling.</b> {missingOutcomes > 0 ? `${missingOutcomes} assessed finding${missingOutcomes === 1 ? '' : 's'} still lack a recorded outcome. This is not a count of fixes completed.` : 'Durable totals remain visible while ACP verifies this snapshot.'}</p>}
  </section>
}
