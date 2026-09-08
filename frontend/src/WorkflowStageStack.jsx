import { useEffect, useMemo, useState } from 'react'
import LiveHeartbeatBars from './LiveHeartbeatBars.jsx'
import WorkflowStageActivityCard from './WorkflowStageActivityCard.jsx'
import { canonicalStageCardModel, canonicalWorkflowStages, currentCanonicalStage,
  stageNeedsAttention } from './canonicalStageCard.js'

const STAGES = ['discover', 'assess', 'remediate', 'release']
const LABELS = { discover: 'Discover', assess: 'Assess', remediate: 'Remediate', release: 'Release' }
const destination = { discover: 'discover', assess: 'assess', remediate: 'remediate', release: 'publish' }
const terminal = (state) => ['succeeded', 'failed', 'cancelled', 'superseded', 'integrity_failed'].includes(state)

function storageKey(lineage) {
  const workflow = lineage?.workflow_id || lineage?.scan_id || 'workflow'
  return `acp:workflow-stage-stack:${workflow}:${lineage?.workflow_revision ?? 'unknown'}`
}

function primaryOutcome(model) {
  if (model.stage === 'discover') return `${model.domain?.total ?? '—'} ${model.domain?.unit || 'inventory documents'}`
  if (model.stage === 'assess') {
    const assessed = model.domain?.buckets.find(([label]) => label === 'Assessed')?.[1]
    return `${assessed ?? '—'} assessed of ${model.domain?.total ?? '—'} eligible documents`
  }
  return `${model.domain?.accounted ?? model.accounted ?? '—'} of ${model.domain?.total ?? model.total ?? '—'} ${model.domain?.unit || model.unit}`
}

/** The sole outer shell for all four workflow stages. Detail nodes stay mounted under `hidden`
 * so disclosure changes do not end live subscriptions or reset rolling heartbeat history. */
export default function WorkflowStageStack({ lineage, onNavigate, receivedAt = null,
  stageDetails = {} }) {
  const snapshots = useMemo(() => canonicalWorkflowStages(lineage), [lineage])
  const current = useMemo(() => currentCanonicalStage(lineage), [lineage])
  const key = storageKey(lineage)
  const [overrides, setOverrides] = useState({})

  useEffect(() => { setOverrides({}) }, [key])

  if (!snapshots.length) return null
  const byStage = new Map(snapshots.map((snapshot) => [snapshot.stage, snapshot]))

  return (
    <section className="workflow-stage-stack" aria-label="Workflow stages"
      data-current-stage={current?.stage || ''}>
      {STAGES.map((stage) => {
        const snapshot = byStage.get(stage)
        const locked = !snapshot
        const isCurrent = Boolean(snapshot && stage === current?.stage
          && snapshot.execution_id === current?.execution_id)
        const model = snapshot ? canonicalStageCardModel(snapshot, { isCurrent }) : null
        const attention = Boolean(snapshot && stageNeedsAttention(snapshot))
        const defaultOpen = attention || isCurrent
        const open = locked ? false : (attention || (overrides[stage] ?? defaultOpen))
        const detail = isCurrent ? stageDetails[stage] : null
        const bodyId = `workflow-stage-${stage}`
        return (
          <div className={`workflow-stage-stack__item${attention ? ' needs-attention' : ''}${isCurrent ? ' is-current' : ''}${locked ? ' is-locked' : ''}`}
               data-stage={stage} data-current={isCurrent ? 'true' : 'false'}
               key={`${stage}:${snapshot?.execution_id || snapshot?.revision || 'locked'}`}>
            {locked ? <div className="workflow-stage-stack__summary" aria-disabled="true">
              <span className="workflow-stage-stack__check" aria-hidden="true">·</span>
              <span className="workflow-stage-stack__label"><b>{LABELS[stage]}</b>
                <span className="workflow-stage-stack__locked-state"> · Locked</span>
              </span>
              <span className="workflow-stage-stack__meta">
                <span className="workflow-stage-stack__ownership">Not started</span>
              </span>
            </div> : <button type="button" className="workflow-stage-stack__summary"
                    aria-expanded={open} aria-controls={bodyId}
                    onClick={() => setOverrides((value) => ({ ...value, [stage]: !open }))}>
              <span className="workflow-stage-stack__check" aria-hidden="true">
                {attention ? '!' : snapshot.state === 'succeeded' ? '✓' : '•'}
              </span>
              <span className="workflow-stage-stack__label"><b>{model.stageLabel}</b> · {model.stateLabel}</span>
              <span className="workflow-stage-stack__meta">
                <span className="muted workflow-stage-stack__count">{primaryOutcome(model)}</span>
                {!open && !terminal(snapshot.state) && <LiveHeartbeatBars measuredAt={receivedAt} stage={stage}
                  historyKey={`${snapshot.workflow_id || lineage?.workflow_id || 'workflow'}:${snapshot.execution_id || stage}`}
                  showText />}
                {isCurrent && <span className="workflow-stage-stack__ownership">Current</span>}
              </span>
              <span className="workflow-stage-stack__affordance" aria-hidden="true">{open ? '−' : '+'}</span>
            </button>}
            {!locked && <div id={bodyId} className="workflow-stage-stack__body" hidden={!open}>
              {detail ? <div className="workflow-stage-stack__live-detail" data-detail-owner="current">{detail}</div>
                : <WorkflowStageActivityCard snapshot={snapshot} receivedAt={receivedAt}
                    onOpen={onNavigate ? () => onNavigate(destination[stage]) : null} />}
            </div>}
          </div>
        )
      })}
    </section>
  )
}
