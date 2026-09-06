import React from 'react'

const LABELS = { discover: 'Discovery', assess: 'Assessment', remediate: 'Remediation', publish: 'Release' }

export function primaryActiveWorkflow(items = []) {
  const priority = { publish: 4, remediate: 3, assess: 2, discover: 1 }
  return [...items].sort((a, b) => {
    const freshness = String(b.updated_at || '').localeCompare(String(a.updated_at || ''))
    return freshness || (priority[b.stage] || 0) - (priority[a.stage] || 0)
  })[0] || null
}

export function workflowRevisionLabel(workflow = {}) {
  const revision = Math.max(1, Number(workflow.workflow_revision || workflow.revision || 1))
  return `Workflow revision ${revision}`
}

export default function WorkflowContinuityBanner({ workflow, currentView, onReturn, onLiveOps, onViewPrevious }) {
  if (!workflow || workflow.stage === currentView) return null
  const label = LABELS[workflow.stage] || 'Work'
  const active = Number(workflow.running || 0)
  const queued = Number(workflow.queued || 0)
  return (
    <section className="workflow-continuity" aria-live="polite" aria-label="Work still in progress">
      <div>
        <strong>{label} is still running</strong>
        <span>{workflowRevisionLabel(workflow)} · {workflow.source} · {active} active{queued ? ` · ${queued} waiting` : ''}</span>
      </div>
      <div className="workflow-continuity-actions">
        <button className="secondary" onClick={() => onReturn(workflow.stage)}>Continue current {label}</button>
        {workflow.previous_scan_id && onViewPrevious && (
          <button className="ghost" onClick={() => onViewPrevious(workflow.previous_scan_id)}>
            View previous revision
          </button>
        )}
        <button className="link-button" onClick={onLiveOps}>View Live Ops</button>
      </div>
    </section>
  )
}
