import React, { useEffect, useRef, useState } from 'react'
import { canonicalStageCardModel } from './canonicalStageCard.js'
import LiveHeartbeatBars from './LiveHeartbeatBars.jsx'
import './canonical-stage-card.css'

const shown = (value) => value == null ? 'Not reported' : value.toLocaleString()

export default function CanonicalStageCard({ snapshot, onOpen = null, embedded = false,
  receivedAt = null }) {
  const model = canonicalStageCardModel(snapshot)
  if (!model) return null
  const accounted = model.domain ? model.domain.accounted : model.accounted
  const total = model.domain ? model.domain.total : model.total
  const unit = model.domain?.unit || model.unit
  const stateTone = model.integrityOk && snapshot?.state === 'succeeded' ? 'is-complete'
    : (!model.integrityOk || model.stopping || ['failed', 'cancelled', 'integrity_failed', 'reconciling', 'processing_complete'].includes(snapshot?.state)
      ? 'needs-attention' : 'is-live')
  const progress = model.integrityOk && typeof accounted === 'number' && typeof total === 'number' && total > 0
    ? Math.max(0, Math.min(100, Math.round((accounted / total) * 100))) : null
  const previous = useRef({ executionId: model.executionId, accounted })
  const [delta, setDelta] = useState(null)
  const terminal = ['succeeded', 'failed', 'cancelled', 'superseded', 'integrity_failed']
    .includes(snapshot?.state)
  const heartbeatKey = `${snapshot?.workflow_id || 'workflow'}:${model.executionId || model.stage}`

  useEffect(() => {
    const before = previous.current
    const change = before.executionId === model.executionId
      && typeof before.accounted === 'number' && typeof accounted === 'number'
      ? accounted - before.accounted : 0
    previous.current = { executionId: model.executionId, accounted }
    setDelta(change > 0 ? change : null)
    if (change <= 0) return undefined
    const timer = setTimeout(() => setDelta(null), 2400)
    return () => clearTimeout(timer)
  }, [accounted, model.executionId])

  const content = <>
      <div className="canonical-stage-card__heading">
        <div>
          {embedded && <strong>{model.stageLabel} · {model.stateLabel}</strong>}
          <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
            Workflow revision {shown(model.workflowRevision)} · snapshot revision {shown(model.revision)}
          </div>
        </div>
        <span className="canonical-stage-card__heartbeat">
          <LiveHeartbeatBars measuredAt={receivedAt} stage={model.stage} historyKey={heartbeatKey}
            terminal={terminal} showText />
        </span>
        {onOpen && <button type="button" className="linklike" onClick={onOpen}>Open details →</button>}
      </div>

      {!model.integrityOk ? (
        <p role="status" style={{ margin: '10px 0 0' }}>
          <b>Accounting temporarily inconsistent.</b> Progress claims are withheld until reconciliation completes.
        </p>
      ) : model.domain ? (<>
        <p style={{ margin: '10px 0 0' }}>
          <b>{shown(model.domain.accounted)} of {shown(model.domain.total)} {model.domain.unit} reconciled</b>
          {model.domain.exact && ' · Exact'}
        </p>
        {model.domain.equation && <p className="muted" style={{ margin: '3px 0 0', fontSize: 12 }}>
          Integrity check: {model.domain.equation}
        </p>}
        <dl aria-label={`${model.stageLabel} domain counts`}
            style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px', margin: '10px 0 0' }}>
          {model.domain.buckets.map(([label, value]) => (
            <div key={label}>
              <dt className="muted">{label}</dt>
              <dd style={{ margin: 0, fontVariantNumeric: 'tabular-nums', fontWeight: 650 }}>
                {shown(value)}
              </dd>
            </div>
          ))}
        </dl>
      </>) : (<>
        <p style={{ margin: '10px 0 0' }}>
          <b>Integrity check: {shown(model.accounted)} of {shown(model.total)} {model.unit} accounted for</b>
          {model.exact && ' · Reconciled'}
        </p>
      </>
      )}

      {model.integrityOk && <details style={{ margin: '10px 0 0' }}>
        <summary className="muted">Operational work-item progress</summary>
        <dl aria-label={`${model.stageLabel} work-item counts`}
            style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px', margin: '8px 0 0' }}>
          {model.workItems.map(([label, value]) => (
            <div key={label}>
              <dt className="muted">{label}</dt>
              <dd style={{ margin: 0, fontVariantNumeric: 'tabular-nums', fontWeight: 650 }}>
                {shown(value)}
              </dd>
            </div>
          ))}
        </dl>
      </details>}

      <dl style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px', margin: '10px 0 0' }}>
        <div><dt className="muted">Execution</dt><dd className="machine-value" style={{ margin: 0 }}>{model.executionId || 'Not reported'}</dd></div>
        <div><dt className="muted">Sealed output</dt><dd className="machine-value" style={{ margin: 0 }}>{model.manifestId || 'Not yet sealed'}</dd></div>
        <div><dt className="muted">Last durable update</dt><dd className="machine-value" style={{ margin: 0 }}>{model.lastUpdatedAt || 'Not reported'}</dd></div>
      </dl>

      <p className="muted" style={{ margin: '8px 0 0', fontSize: 12 }}>
        Work-item completion reports execution progress. It does not mean every accessibility finding was resolved.
      </p>
  </>

  if (embedded) {
    return <div aria-label={`${model.stageLabel} canonical stage status`}
      data-testid="canonical-stage-card">{content}</div>
  }

  return (
    <section className={`panel canonical-stage-card stage-${model.stage}`} aria-label={`${model.stageLabel} canonical stage status`}
      data-testid="canonical-stage-card">
      <details>
        <summary className="canonical-stage-card__summary">
          <span className="canonical-stage-card__stage">{model.stageLabel}</span>
          <span aria-hidden="true" className="canonical-stage-card__separator">·</span>
          <span className={`canonical-stage-card__state ${stateTone}`}>{model.stateLabel}</span>
          <span className="canonical-stage-card__count">
            {shown(accounted)} of {shown(total)} {unit}
            {delta != null && <span key={`${model.revision}-${delta}`} className="canonical-stage-card__delta"
              role="status" aria-label={`${delta} newly reconciled`}>+{delta}</span>}
          </span>
          <span className="canonical-stage-card__hint">View accounting</span>
          <LiveHeartbeatBars measuredAt={receivedAt} stage={model.stage} historyKey={heartbeatKey}
            terminal={terminal} showText />
          <span className="canonical-stage-card__chevron" aria-hidden="true">⌄</span>
          {progress != null && <span className="canonical-stage-card__progress" aria-hidden="true">
            <span style={{ width: `${progress}%` }} />
          </span>}
        </summary>
        <div className="canonical-stage-card__body">{content}</div>
      </details>
    </section>
  )
}
