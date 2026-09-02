// Remediate's own instance of the "Processing status" panel derivation — see processingState.js
// (Assess) and discoverProcessingState.js (Discover) for the two existing siblings this follows.
// Same shape (state/headline/detail/recommendedAction/severity/pickupUnavailable), fed into the
// SAME ProcessingStatusPanel component.
//
// Only ONE live state is reachable here, unlike Assess/Discover's richer ladders. Remediate.jsx
// already has its own real-time progress bar once files start completing (`remProg.done > 0`,
// rendered directly below the Remediate button) and its own `remMsg` banner for completion and
// no-capacity — duplicating either here would just be a second counter on the same screen saying
// the same thing a different way. This panel exists for the one window neither of those covers:
// after clicking Remediate, before the first document finishes, when the metric cards still read
// all-zero and nothing on screen says when that will change.
import { fmtPickupRange } from './pickupEstimateFmt.js'

export function deriveRemediateProcessingState({
  remBusy = false, remProg = null,
  updateMode = 'idle',
  // GET /scans/{id}/queue-estimate?kind=remediate's own result — see discoverProcessingState.js's
  // identical param for the full reasoning. insufficient_history or an unresolved fetch leave
  // pickupUnavailable at its default true rather than a placeholder range.
  pickupEstimate = null,
} = {}) {
  const total = remProg?.total ?? 0
  const done = remProg?.done ?? 0
  if (!remBusy && !remProg) {
    return { state: 'idle', headline: null, detail: null, recommendedAction: null, severity: 'info' }
  }
  if (done > 0) {
    return {
      state: 'active', headline: `Applying fixes — ${done} of ${total} complete`,
      detail: remProg?.activity?.text || (remProg?.latest ? `Last completed: ${remProg.latest}` : null),
      recommendedAction: null, severity: 'active', live: updateMode === 'live',
      next: 'ACP re-checks each corrected document before marking its findings complete.',
    }
  }
  const pickupRange = pickupEstimate?.state === 'estimated' && pickupEstimate.earliest_at && pickupEstimate.latest_at
    ? fmtPickupRange(pickupEstimate.earliest_at, pickupEstimate.latest_at) : null
  return {
    state: 'waiting',
    headline: 'Waiting for a worker',
    detail: `${total} document${total === 1 ? '' : 's'} queued for remediation.`
      + (pickupRange ? ` Estimated pickup: ${pickupRange}.` : ''),
    recommendedAction: null,
    severity: 'waiting',
    pickupUnavailable: !pickupRange,
    // The backend queue-estimate route's own capacity check — Remediate.jsx's own no-capacity
    // early return only ever runs once, at the initial enqueue; this can catch capacity dropping
    // to zero after that, while still queued.
    noWorkerAvailable: pickupEstimate?.state === 'no_worker_available',
    live: updateMode === 'live',
  }
}
