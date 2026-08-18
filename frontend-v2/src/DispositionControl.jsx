import { useState } from 'react'
import { DISPOSITION, normalizeDisposition, dispositionByKey } from './disposition.js'

// W4 — the per-criterion control that turns a dead-end box (UNCHECKED / GAP / AT) into a resolved,
// documented state. Two lanes, each requiring a REASON:
//   • Attest conformance   — a human verified it out-of-band (manual audit / screen-reader pass)
//   • Mark out of scope    — the criterion isn't part of this engagement's certification target
//
// It renders the recorded disposition once one exists (with its reason and, if known, who/when);
// otherwise it offers the two actions, each opening a small reason field. `onSave(kind, reason)`
// returns a promise; a truthy resolve is treated as success. Kept a standalone component so the
// behaviour is unit-tested directly, not only through the very heavy FileDrawer mount.
export default function DispositionControl({ sc, disposition = null, onSave, disabled = false }) {
  const recorded = normalizeDisposition(disposition)
  const [open, setOpen] = useState(null)   // null | 'attested' | 'out_of_scope'
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (recorded) {
    const meta = dispositionByKey(recorded.kind)
    return (
      <span className={`covdisp covdisp-${recorded.kind}`} title={`${meta.label}${recorded.actor ? ` · ${recorded.actor}` : ''}${recorded.at ? ` · ${recorded.at}` : ''}`}>
        <b>{meta.glyph} {meta.label}</b>
        <span className="muted"> — {recorded.reason}</span>
      </span>
    )
  }

  const start = (kind) => { setOpen(kind); setReason(''); setError(null) }
  const cancel = () => { setOpen(null); setReason(''); setError(null) }
  const save = async () => {
    const r = reason.trim()
    if (!r) { setError('A reason is required — it becomes part of the audit record.'); return }
    setBusy(true); setError(null)
    try {
      const res = await onSave?.(open, r)
      if (res) { setOpen(null); setReason('') }
      else setError('Could not record this — try again.')
    } catch {
      setError('Could not record this — try again.')
    } finally {
      setBusy(false)
    }
  }

  if (open) {
    const meta = dispositionByKey(open)
    return (
      <span className="covdisp-form" style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 5, alignItems: 'center', marginLeft: 6 }}>
        <label className="muted" style={{ fontSize: 11 }}>{meta.verb}:</label>
        <input type="text" aria-label={`${meta.verb} reason for ${sc}`} value={reason} disabled={busy}
               placeholder={open === 'attested' ? 'How was it verified? (e.g. NVDA pass)' : 'Why is it out of scope?'}
               onChange={(e) => setReason(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel() }}
               style={{ fontSize: 11, padding: '2px 6px', minWidth: 180 }} />
        <button type="button" className="explain-btn" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>
        <button type="button" className="explain-btn" disabled={busy} onClick={cancel}>Cancel</button>
        {error && <span role="alert" className="muted" style={{ color: '#B43A2A', fontSize: 11, flexBasis: '100%' }}>{error}</span>}
      </span>
    )
  }

  return (
    <span className="covdisp-actions" style={{ marginLeft: 6, display: 'inline-flex', gap: 4 }}>
      <button type="button" className="explain-btn" disabled={disabled}
              title="Record that a human verified this criterion out-of-band (writes a documented decision)"
              onClick={() => start('attested')}>{DISPOSITION.ATTESTED.verb}</button>
      <button type="button" className="explain-btn" disabled={disabled}
              title="Record that this criterion is out of this engagement's certification scope"
              onClick={() => start('out_of_scope')}>{DISPOSITION.OUT_OF_SCOPE.verb}</button>
    </span>
  )
}
