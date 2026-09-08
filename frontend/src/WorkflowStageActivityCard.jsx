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
  const live = !terminal(snapshot.state)
  return <section className={`workflow-sse-card stage-${model.stage}`} aria-label={`${model.stageLabel} activity`}>
    <header className="workflow-sse-card__header">
      <div><strong>{model.stageLabel} · {model.stateLabel}</strong>
        <span>Workflow revision {model.workflowRevision ?? '—'}</span></div>
      {live && <LiveHeartbeatBars measuredAt={receivedAt} stage={model.stage}
        historyKey={`${snapshot.workflow_id || 'workflow'}:${model.executionId || model.stage}`} showText />}
      {onOpen && <button type="button" className="linklike" onClick={onOpen}>Open details →</button>}
    </header>
    <p className="workflow-sse-card__outcome"><b>{shown(done)} of {shown(total)}</b> {domain?.unit || model.unit}</p>
    <div className="workflow-sse-card__track" aria-label={`${pct}% complete`} role="progressbar"
      aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct}><span style={{ width: `${pct}%` }} /></div>
    {domain?.buckets?.length > 0 && <dl className="workflow-sse-card__metrics">
      {domain.buckets.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{shown(value)}</dd></div>)}
    </dl>}
    {!model.integrityOk && <p className="workflow-sse-card__notice"><b>Accounting is reconciling.</b> Durable totals remain visible while ACP verifies this snapshot.</p>}
  </section>
}
