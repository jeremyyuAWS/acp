import { useState, useEffect } from 'react'
import { getWorkerReplicas, setWorkerReplicas } from './api.js'

// Azure Container App replica control (min warm replicas for acp-worker, 1-5). Self-contained:
// fetches its own snapshot on mount and owns the adjust/rollback logic, so any screen can mount
// it with no props and no coordination with the caller's own state. Renders nothing when Azure
// replica control isn't configured on the backend (no AZURE_SUBSCRIPTION_ID) — matches
// GET /control/workers/replicas's own `configured: false` contract.
//
// Extracted from AssessRunner.jsx (2026-08-28) so the same control could be reused in Settings'
// worker-transparency section — someone adjusting warm capacity ahead of a big scan should not
// need an assessment already running to find the knob. AssessRunner still mounts this in the
// same conditional position it always rendered its own inline version in (inside its
// `workerSnap &&` block), so the effective gating is unchanged.
export default function WorkerReplicaControl({ leadingSeparator = false } = {}) {
  const [snap, setSnap] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let on = true
    getWorkerReplicas().then((d) => { if (on && d.configured) setSnap(d) }).catch(() => {})
    return () => { on = false }
  }, [])

  const adjust = (delta) => {
    if (!snap || busy) return
    const next = Math.max(1, Math.min(snap.max_replicas ?? 5, snap.min_replicas + delta))
    if (next === snap.min_replicas) return
    const prev = snap.min_replicas
    setBusy(true)
    setSnap((s) => ({ ...s, min_replicas: next }))   // optimistic
    setWorkerReplicas(next)
      .then((d) => setSnap(d))
      .catch(() => setSnap((s) => ({ ...s, min_replicas: prev })))
      .finally(() => setBusy(false))
  }

  if (!snap) return null
  return (
    <>
    {leadingSeparator && <span className="muted">·</span>}
    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <button onClick={() => adjust(-1)} disabled={busy || snap.min_replicas <= 1}
              aria-label="Remove a Container App replica"
              style={{ width: 20, height: 20, borderRadius: 5, border: '1px solid var(--line)',
                       background: '#fff', color: 'var(--ink)', fontSize: 14, lineHeight: 1,
                       cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 0 }}>−</button>
      <span style={{ fontSize: 13, fontWeight: 600, minWidth: 14, textAlign: 'center' }}>{snap.min_replicas}</span>
      <button onClick={() => adjust(+1)} disabled={busy || snap.min_replicas >= (snap.max_replicas ?? 5)}
              aria-label="Add a Container App replica"
              style={{ width: 20, height: 20, borderRadius: 5, border: '1px solid var(--line)',
                       background: '#fff', color: 'var(--ink)', fontSize: 14, lineHeight: 1,
                       cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 0 }}>+</button>
      <span className="muted" style={{ fontSize: 11 }}>Azure replicas (max {snap.max_replicas})</span>
    </span>
    </>
  )
}
