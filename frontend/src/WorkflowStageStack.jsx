import { useEffect, useMemo, useState } from 'react'
import CanonicalStageCard from './CanonicalStageCard.jsx'
import LiveHeartbeatBars from './LiveHeartbeatBars.jsx'
import { canonicalStageCardModel, priorCanonicalStages, stageNeedsAttention } from './canonicalStageCard.js'

const destination = { discover: 'discover', assess: 'assess', remediate: 'remediate', release: 'publish' }

function storageKey(lineage) {
  const workflow = lineage?.workflow_id || lineage?.scan_id || 'workflow'
  return `acp:workflow-stage-stack:${workflow}:${lineage?.workflow_revision ?? 'unknown'}`
}

export default function WorkflowStageStack({ lineage, view, onNavigate, receivedAt = null }) {
  const stages = useMemo(() => priorCanonicalStages(lineage, view), [lineage, view])
  const attentionStage = stages.find(stageNeedsAttention)?.stage || null
  const key = storageKey(lineage)
  const [expanded, setExpanded] = useState(() => {
    try { return sessionStorage.getItem(key) } catch { return null }
  })

  useEffect(() => {
    let remembered = null
    try { remembered = sessionStorage.getItem(key) } catch {}
    setExpanded((current) => {
      const candidate = remembered || current
      return attentionStage || (stages.some((stage) => stage.stage === candidate) ? candidate : null)
    })
  }, [attentionStage, key, stages])

  useEffect(() => {
    try {
      if (expanded) sessionStorage.setItem(key, expanded)
      else sessionStorage.removeItem(key)
    } catch {}
  }, [expanded, key])

  if (!stages.length) return null
  return (
    <section className="workflow-stage-stack" aria-label="Earlier workflow stages">
      <div className="workflow-stage-stack__heading">
        <strong>Workflow so far</strong>
        <span className="muted">Earlier stages from this workflow revision</span>
      </div>
      {stages.map((snapshot) => {
        const model = canonicalStageCardModel(snapshot)
        const open = expanded === snapshot.stage
        return (
          <div className={`workflow-stage-stack__item${stageNeedsAttention(snapshot) ? ' needs-attention' : ''}`}
               key={`${snapshot.stage}:${snapshot.execution_id || snapshot.revision}`}>
            <button type="button" className="workflow-stage-stack__summary"
                    aria-expanded={open}
                    aria-controls={`workflow-stage-${snapshot.stage}`}
                    onClick={() => setExpanded(open ? null : snapshot.stage)}>
              <span className="workflow-stage-stack__check" aria-hidden="true">
                {stageNeedsAttention(snapshot) ? '!' : '✓'}
              </span>
              <span><b>{model.stageLabel}</b> · {model.stateLabel}</span>
              <span className="muted workflow-stage-stack__count">
                {model.domain?.accounted ?? model.accounted ?? '—'} of {model.domain?.total ?? model.total ?? '—'} {model.domain?.unit || model.unit}
              </span>
              <LiveHeartbeatBars measuredAt={receivedAt} stage={model.stage}
                historyKey={`${snapshot.workflow_id || lineage?.workflow_id || 'workflow'}:${snapshot.execution_id || snapshot.stage}`}
                terminal={['succeeded', 'failed', 'cancelled', 'superseded', 'integrity_failed'].includes(snapshot.state)}
                showText />
              <span aria-hidden="true">{open ? '−' : '+'}</span>
            </button>
            {open && (
              <div id={`workflow-stage-${snapshot.stage}`} className="workflow-stage-stack__body">
                <CanonicalStageCard snapshot={snapshot} receivedAt={receivedAt}
                  onOpen={onNavigate ? () => onNavigate(destination[snapshot.stage]) : null} embedded />
              </div>
            )}
          </div>
        )
      })}
    </section>
  )
}
