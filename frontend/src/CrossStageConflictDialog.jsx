import { useEffect, useId, useRef } from 'react'
import { STAGE_CONFLICT_DECISION } from './stageExecutionConflict.js'

const STAGE_LABELS = { discover: 'Discovery', assess: 'Assessment', remediate: 'Remediation', conformance: 'Conformance', release: 'Release' }

const stageName = (stage, fallback) => {
  const value = String(stage || fallback).trim()
  return STAGE_LABELS[value.toLowerCase()] || (value.charAt(0).toUpperCase() + value.slice(1))
}

export default function CrossStageConflictDialog({
  conflict,
  requestedStage,
  activeStage,
  busy = false,
  error = '',
  onDecision,
}) {
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef(null)
  const returnFocus = useRef(null)
  const decisionRef = useRef(onDecision)
  const busyRef = useRef(busy)
  decisionRef.current = onDecision
  busyRef.current = busy

  useEffect(() => {
    if (!conflict) return undefined
    returnFocus.current = document.activeElement
    const dialog = dialogRef.current
    dialog?.querySelector('[data-default-action]')?.focus()
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && !busyRef.current) {
        event.preventDefault()
        decisionRef.current(STAGE_CONFLICT_DECISION.CANCEL)
        return
      }
      if (event.key !== 'Tab' || !dialog) return
      const controls = [...dialog.querySelectorAll('button:not([disabled])')]
      if (!controls.length) return
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      const opener = returnFocus.current
      if (opener?.isConnected) queueMicrotask(() => opener.focus())
    }
  }, [conflict])

  if (!conflict) return null
  const requested = stageName(requestedStage, 'upstream stage')
  const active = stageName(activeStage || conflict.currentStage, 'downstream stage')
  const choose = (decision) => { if (!busy) onDecision(decision) }
  const button = { borderRadius: 8, padding: '10px 14px', fontWeight: 650, fontSize: 14, cursor: busy ? 'wait' : 'pointer' }

  return (
    <div role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) choose(STAGE_CONFLICT_DECISION.CANCEL)
    }} style={{ position: 'fixed', inset: 0, zIndex: 10000, display: 'grid', placeItems: 'center', padding: 20,
      background: 'rgba(15,23,42,.62)' }}>
      <section ref={dialogRef} role="alertdialog" aria-modal="true" aria-labelledby={titleId}
        aria-describedby={descriptionId} aria-busy={busy || undefined}
        style={{ width: 'min(560px,100%)', borderRadius: 14, background: '#fff', color: '#172033',
          boxShadow: '0 28px 72px rgba(0,0,0,.38)', overflow: 'hidden' }}>
        <div style={{ padding: '20px 22px', background: '#fff7ed', borderBottom: '1px solid #fed7aa' }}>
          <h2 id={titleId} style={{ margin: 0, fontSize: 20 }}>A later workflow stage is still active</h2>
        </div>
        <div style={{ padding: '20px 22px 10px' }}>
          <p id={descriptionId} style={{ margin: 0, lineHeight: 1.55 }}>
            Starting {requested} now conflicts with the active {active} execution. Choose which work should continue.
          </p>
          <p style={{ margin: '12px 0 0', color: '#64748b', fontSize: 13, overflowWrap: 'anywhere' }}>
            Active execution: {conflict.currentExecutionId}
          </p>
          {error && <p role="alert" style={{ margin: '14px 0 0', padding: 10, borderRadius: 8,
            background: '#fef2f2', color: '#991b1b' }}>{error}</p>}
        </div>
        <div style={{ padding: '14px 22px 22px', display: 'grid', gap: 10 }}>
          <button type="button" data-default-action disabled={busy}
            onClick={() => choose(STAGE_CONFLICT_DECISION.CONTINUE)}
            style={{ ...button, border: '1px solid #2563eb', background: '#2563eb', color: '#fff' }}>
            Continue {active}
          </button>
          <button type="button" disabled={busy}
            onClick={() => choose(STAGE_CONFLICT_DECISION.RESTART)}
            style={{ ...button, border: '1px solid #c2410c', background: '#fff', color: '#9a3412' }}>
            Stop {active} and start a new workflow revision
          </button>
          <button type="button" disabled={busy}
            onClick={() => choose(STAGE_CONFLICT_DECISION.CANCEL)}
            style={{ ...button, border: '1px solid #cbd5e1', background: '#fff', color: '#475569' }}>
            Cancel
          </button>
        </div>
      </section>
    </div>
  )
}
