import React from 'react'

const LABELS = { discover: 'Discovery', assess: 'Assessment', remediate: 'Remediation' }

export function primaryActiveWorkflow(items = []) {
  const priority = { remediate: 3, assess: 2, discover: 1 }
  return [...items].sort((a, b) => {
    const freshness = String(b.updated_at || '').localeCompare(String(a.updated_at || ''))
    return freshness || (priority[b.stage] || 0) - (priority[a.stage] || 0)
  })[0] || null
}

export default function WorkflowContinuityBanner({ workflow, currentView, onReturn, onLiveOps }) {
  if (!workflow || workflow.stage === currentView) return null
  const label = LABELS[workflow.stage] || 'Work'
  const active = Number(workflow.running || 0)
  const queued = Number(workflow.queued || 0)
  return (
    <section className="workflow-continuity" aria-live="polite" aria-label="Work still in progress">
      <div>
        <strong>{label} is still running</strong>
        <span>{workflow.source} · {active} active{queued ? ` · ${queued} waiting` : ''}</span>
      </div>
      <div className="workflow-continuity-actions">
        <button className="secondary" onClick={() => onReturn(workflow.stage)}>Return to {label}</button>
        <button className="link-button" onClick={onLiveOps}>View Live Ops</button>
      </div>
    </section>
  )
}
