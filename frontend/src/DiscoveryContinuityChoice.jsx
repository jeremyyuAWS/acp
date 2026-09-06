import React from 'react'

export default function DiscoveryContinuityChoice({ choice, onContinue, onReplace, onDismiss }) {
  if (!choice) return null
  const recent = choice.recentCompatible === true
  const stage = ['assess', 'remediate', 'publish'].includes(choice.activeStage)
    ? choice.activeStage : 'discover'
  const stageLabel = { discover: 'Discovery', assess: 'Assessment', remediate: 'Remediation', publish: 'Release' }[stage]
  return (
    <section className="panel" role="alertdialog" aria-labelledby="discovery-continuity-title"
             aria-describedby="discovery-continuity-copy"
             style={{ marginBottom: 12, borderLeft: '4px solid var(--accent, #6D28D9)', background: 'var(--surface)' }}>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 420px' }}>
          <strong id="discovery-continuity-title">{recent ? 'A matching workflow just ran' : `${stageLabel} is already running`}</strong>
          <div id="discovery-continuity-copy" className="muted" style={{ marginTop: 3, fontSize: 12.5 }}>
            {recent
              ? 'The source, folders, settings, and lifecycle policy match. Continue that workflow to avoid repeating Discovery, or intentionally create a new revision.'
              : `Continue the current ${stageLabel} to keep its progress. Starting a new Discovery will stop it and create a new workflow revision.`}
          </div>
          <div className="muted" style={{ marginTop: 5, fontSize: 11.5, fontFamily: 'monospace' }}>
            Workflow revision {choice.workflowRevision || 1} · Scan {choice.scanId}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" onClick={onContinue}>Continue current {stageLabel}</button>
          <button type="button" className="secondary" onClick={onReplace}>
            {stage === 'discover' || recent ? 'Start revised Discovery' : `Cancel ${stageLabel} and start new Discovery`}
          </button>
          <button type="button" className="ghost small" onClick={onDismiss}>Keep current screen</button>
        </div>
      </div>
    </section>
  )
}
