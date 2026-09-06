import { useEffect, useState } from 'react'
import { getCapacitySchedule } from './api.js'

/**
 * Live Operations → the capacity mode, READ-ONLY and with no control of any kind.
 *
 * WHY IT IS HERE AND WHY IT IS NOT THE EDITOR. The Scheduling PRD (§4, §10, AC 1) puts the
 * schedule in Settings and keeps live operational state in Monitor; this repository enforces the
 * same split, with queuePanelCapacity.test.jsx asserting that no capacity adjust control renders
 * outside Settings → Worker Configuration. But "which capacity mode are we in, and when does it
 * change?" is a question operators ask while looking at Live Operations, and sending them to
 * Settings to read one line is how a schedule becomes something nobody checks.
 *
 * So: the answer here, the controls there. Review finding R1 of docs/prd-capacity-scheduling.md.
 *
 * RENDERS NOTHING when the schedule cannot be read or is not applied. A strip announcing a
 * proposed schedule beside live traffic would be read as describing that traffic, which is the
 * one misreading this surface cannot afford — the numbers next to it are real.
 */
export default function CapacityModeStrip() {
  const [snap, setSnap] = useState(null)

  useEffect(() => {
    let on = true
    // A STATUS STRIP MUST NEVER TAKE LIVE OPERATIONS DOWN WITH IT. The try/catch is not
    // belt-and-braces around the .catch: a fetch helper that is missing or throws SYNCHRONOUSLY
    // never returns a promise, so .catch is not reached and the error propagates out of the
    // effect to the ErrorBoundary — which unmounts the infrastructure map, the worker services
    // and the running-jobs view along with this one line. Losing the whole operations view to
    // decoration is the wrong trade in every case; the strip renders nothing instead.
    try {
      getCapacitySchedule().then((d) => { if (on) setSnap(d) }).catch(() => {})
    } catch {
      /* nothing to show; the schedule lives in Settings → Scheduling either way */
    }
    return () => { on = false }
  }, [])

  // `applied` is the gate, not `enabled`: a schedule can be enabled in a proposal that nothing
  // has put into force, and this strip sits among figures that are all live.
  if (!snap?.applied) return null

  const mode = snap.effective_mode === 'business_hours' ? 'Business-hours capacity'
    : 'Off-hours capacity'
  const drifted = snap.drift_evaluated && !!snap.drift?.length

  return (
    <div role="status" aria-label="Capacity mode" className="chip"
      style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12,
               fontSize: 12, padding: '7px 11px' }}>
      <b>{mode}</b>
      <span className="muted">{snap.timezone}</span>
      {snap.next_transition_at && (
        <span className="muted">
          · next change {new Date(snap.next_transition_at).toLocaleString()}
        </span>
      )}
      {/* Drift is stated here rather than only in Settings because this is where somebody is
          looking when the replica counts do not match what they expected. */}
      {drifted && (
        <span style={{ color: 'var(--warn-fg, #8a5a00)', fontWeight: 600 }}>
          · configuration drift on {snap.drift.length} setting{snap.drift.length === 1 ? '' : 's'}
        </span>
      )}
      <span className="muted">· schedule in Settings → Scheduling</span>
    </div>
  )
}
