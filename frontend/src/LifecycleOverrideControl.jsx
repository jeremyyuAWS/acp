import { useState } from 'react'

// Lifecycle rules #8 — per-file override. Mirrors DispositionControl.jsx's shape exactly (W4's
// "documented decision" pattern): one action, requires a reason, renders the recorded override
// permanently once one exists rather than offering the control again.
//
// Deliberately NOT a state machine: overriding a rule's recommendation does not change the
// recommendation shown in the row next to it, and does not move, archive or delete anything —
// same "nothing is moved, this is a recommendation" discipline as everywhere else on this
// screen. It records that a human reviewed the recommendation and disagreed, and why.
export default function LifecycleOverrideControl({ file, override = null, onSave, disabled = false }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (override) {
    const title = `Overridden${override.actor ? ` · ${override.actor}` : ''}${override.at ? ` · ${override.at}` : ''}`
    return (
      <span className="lc-override lc-override-recorded" title={title}>
        <b>✓ Kept</b>
        <span className="muted"> — {override.reason}</span>
      </span>
    )
  }

  const start = () => { setOpen(true); setReason(''); setError(null) }
  const cancel = () => { setOpen(false); setReason(''); setError(null) }
  const save = async () => {
    const r = reason.trim()
    if (!r) { setError('A reason is required — it becomes part of the audit record.'); return }
    setBusy(true); setError(null)
    try {
      const res = await onSave?.(file, r)
      if (res) { setOpen(false); setReason('') }
      else setError('Could not record this — try again.')
    } catch {
      setError('Could not record this — try again.')
    } finally {
      setBusy(false)
    }
  }

  if (open) {
    return (
      <span className="lc-override-form" style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
        <input type="text" aria-label={`Override reason for ${file}`} value={reason} disabled={busy}
               placeholder="Why keep this despite the rule?"
               onChange={(e) => setReason(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel() }}
               style={{ fontSize: 11, padding: '2px 6px', minWidth: 160 }} />
        <button type="button" className="explain-btn" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>
        <button type="button" className="explain-btn" disabled={busy} onClick={cancel}>Cancel</button>
        {error && <span role="alert" className="muted" style={{ color: 'var(--error-fg)', fontSize: 11, flexBasis: '100%' }}>{error}</span>}
      </span>
    )
  }

  return (
    <button type="button" className="explain-btn" disabled={disabled}
            title="Record that you reviewed this recommendation and are keeping the file, with why (writes a documented decision)"
            onClick={start}>Keep this file</button>
  )
}
