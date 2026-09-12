import LiveCounter from './LiveCounter.jsx'
import './finding-outcome-kpis.css'
import LiveHeartbeatBars from './LiveHeartbeatBars.jsx'
import { canonicalStageCardModel, alignRemediationAssessment } from './canonicalStageCard.js'

const terminal = (state) => ['processing_complete', 'succeeded', 'failed', 'cancelled', 'superseded', 'integrity_failed'].includes(state)
const shown = (value) => value == null ? '—' : Number(value).toLocaleString()

export default function WorkflowStageActivityCard({ snapshot, receivedAt, onOpen, progressHostId = null, progressScanId }) {
  const model = canonicalStageCardModel(alignRemediationAssessment(snapshot, null))
  if (!model) return null
  const domain = model.domain
  const done = domain?.accounted ?? model.accounted
  const total = domain?.total ?? model.total
  const pct = typeof done === 'number' && typeof total === 'number' && total > 0
    ? Math.max(0, Math.min(100, Math.round(done / total * 100))) : 0
  const findingAccounting = model.stage === 'remediate' && !!domain
  const missingOutcomes = findingAccounting && Number.isSafeInteger(total) && Number.isSafeInteger(done) && total > done ? total - done : 0
  const balanced = findingAccounting && Number.isSafeInteger(total) && Number.isSafeInteger(done)
    && done >= 0 && done <= total && domain.buckets.every(([, value]) => Number.isSafeInteger(value) && value >= 0)
    && domain.buckets.reduce((sum, [, value]) => sum + value, 0) === total
  const verified = snapshot.domain_reconciliation?.buckets?.resolved_verified ?? 0
  const remaining = balanced && Number.isSafeInteger(verified) && verified >= 0 && verified <= total ? total - verified : null
  const live = !terminal(snapshot.state)
  return <section className={`workflow-sse-card stage-${model.stage}`} aria-label={`${model.stageLabel} activity`}>
    <header className="workflow-sse-card__header">
      <div><strong>{model.stageLabel} · {model.stateLabel}</strong>
        <span>Workflow revision {model.workflowRevision ?? '—'}</span></div>
      {live && <LiveHeartbeatBars measuredAt={receivedAt} stage={model.stage}
        historyKey={`${snapshot.workflow_id || 'workflow'}:${model.executionId || model.stage}`} showText />}
      {onOpen && <button type="button" className="linklike" onClick={onOpen}>Open details →</button>}
    </header>
    <p className="workflow-sse-card__outcome">{findingAccounting
      ? <><b>{shown(total)} assessed findings</b> · Outcome breakdown</>
      : <><b>{shown(done)} of {shown(total)}</b> {domain?.unit || model.unit}</>}</p>
    {findingAccounting && <p className="workflow-sse-card__notice">{live ? 'Verified totals update as document work progresses.' : 'Automatic document work has stopped; remaining findings still need review or remediation.'} Outcomes show what happened to the findings. Document categories show how they can be remediated; individual bucket counts can differ.</p>}
    {model.stage === 'remediate' && progressHostId && <div id={progressHostId} data-scan-id={progressScanId} data-batch-id={model.executionId} aria-label="Document progress summary" />}
    {findingAccounting && !progressHostId && <div className="finding-outcome-kpis" aria-label="Finding totals">
      <div><span>Total assessed</span><strong>{shown(total)}</strong></div>
      <div className="finding-outcome-kpis__verified"><span>Verified fixed</span><strong>{remaining == null ? '—' : <LiveCounter key={model.executionId || model.workflowRevision} value={verified} />}</strong></div>
      <div className="finding-outcome-kpis__remaining"><span>Remaining · not verified</span><strong>{shown(remaining)}</strong></div>
      <p>{remaining == null ? 'Finding totals are being reconciled; remaining is not yet confirmed.' : `${shown(verified)} verified fixed + ${shown(remaining)} remaining = ${shown(total)} assessed findings.`} Remaining includes review, manual work, excluded findings, and findings without a verified fix. These are findings, not change records.</p>
    </div>}
    <div className="workflow-sse-card__track" aria-label={`${pct}% ${findingAccounting ? 'with recorded outcomes' : 'complete'}`} role="progressbar"
      aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct}><span style={{ width: `${pct}%` }} /></div>
    {domain?.buckets?.length > 0 && <dl className="workflow-sse-card__metrics">
      {domain.buckets.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{shown(value)}</dd></div>)}
    </dl>}
    {balanced && <p className="workflow-sse-card__notice">
      {domain.buckets.filter(([, value]) => value > 0).map(([label, value]) => `${shown(value)} ${label.toLowerCase()}`).join(' + ') || '0'} = {shown(total)} assessed findings.
      <br />{shown(done)} with recorded outcomes + {shown(missingOutcomes)} awaiting an outcome = {shown(total)} assessed findings.
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
