import React from 'react'
import { canonicalStageCardModel } from './canonicalStageCard.js'

const shown = (value) => value == null ? 'Not reported' : value.toLocaleString()

export default function CanonicalStageCard({ snapshot, onOpen = null }) {
  const model = canonicalStageCardModel(snapshot)
  if (!model) return null
  return (
    <section className="panel" aria-label={`${model.stageLabel} canonical stage status`}
             data-testid="canonical-stage-card" style={{ margin: '10px 0 0', padding: '12px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <strong>{model.stageLabel} · {model.stateLabel}</strong>
          <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
            Workflow revision {shown(model.workflowRevision)} · snapshot revision {shown(model.revision)}
          </div>
        </div>
        {onOpen && <button type="button" className="linklike" onClick={onOpen}>Open details →</button>}
      </div>

      {!model.integrityOk ? (
        <p role="status" style={{ margin: '10px 0 0' }}>
          <b>Accounting temporarily inconsistent.</b> Progress claims are withheld until reconciliation completes.
        </p>
      ) : (
        <p style={{ margin: '10px 0 0' }}>
          <b>{shown(model.accounted)} of {shown(model.total)} {model.unit} accounted for</b>
          {model.exact && ' · Reconciled'}
        </p>
      )}

      <dl style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px', margin: '10px 0 0' }}>
        <div><dt className="muted">Execution</dt><dd style={{ margin: 0 }}>{model.executionId || 'Not reported'}</dd></div>
        <div><dt className="muted">Sealed output</dt><dd style={{ margin: 0 }}>{model.manifestId || 'Not yet sealed'}</dd></div>
        <div><dt className="muted">Last durable update</dt><dd style={{ margin: 0 }}>{model.lastUpdatedAt || 'Not reported'}</dd></div>
      </dl>

      <p className="muted" style={{ margin: '8px 0 0', fontSize: 12 }}>
        Work-item completion reports execution progress. It does not mean every accessibility finding was resolved.
      </p>
    </section>
  )
}
