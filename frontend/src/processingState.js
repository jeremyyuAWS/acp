// Derives a single plain-language processing state for the "Processing details" panel from
// signals AssessRunner already computes and displays piecemeal (worker service heartbeat, local
// worker count, per-scan queue counts, last-activity recency, current document/stage). PRD
// principle: "Explain status before showing metrics" — lead with one sentence, not a pile of
// numbers the reader has to synthesize themselves.
//
// Deliberately NOT the full PRD state model (Submitted/Scheduled/Retrying/Blocked/Degraded/...).
// Those states need signals this app does not yet track per-scan (retry eligibility time, a
// blocked-on-dependency flag, a distinct stale-worker-lease signal) — inventing them now would be
// exactly the false precision the PRD itself warns against (§2, §9.3). This covers only the
// states this component can actually substantiate today: idle, no_capacity, stalled, completed,
// assessing, waiting.

import { fmtPickupRange } from './pickupEstimateFmt.js'

export function deriveProcessingState({
  phase, noCapacity, stalled, completedCount = 0, totalCount = 0, processingCount = 0,
  waitingCount = 0, lastActivityMins = null, currentFile = null, currentPhase = null,
  // GET /scans/{id}/queue-estimate?kind=assess's own result (AssessRunner.jsx's pickupEstimate
  // state) — see discoverProcessingState.js's identical param for the full reasoning. Only
  // meaningful in the `waiting` branch below: `no_capacity` already means no worker exists to
  // estimate against, which is exactly what the backend's own no_worker_available state would
  // say too, so that branch is left alone rather than asking the estimate to repeat the same
  // fact a second way.
  pickupEstimate = null,
} = {}) {
  if (phase !== 'running') {
    return { state: 'idle', headline: null, detail: null, recommendedAction: null, severity: 'info' }
  }
  if (noCapacity) {
    const remaining = Math.max(0, totalCount - completedCount)
    return {
      state: 'no_capacity',
      headline: 'Waiting for a worker',
      detail: `${remaining} document${remaining === 1 ? '' : 's'} queued — no worker is currently `
        + 'online to process them.',
      recommendedAction: 'start_workers',
      severity: 'blocked',
      pickupUnavailable: true,
    }
  }
  if (stalled) {
    const remaining = Math.max(0, totalCount - completedCount)
    return {
      state: 'stalled',
      headline: 'Assessment may be stalled',
      detail: 'No worker has started or completed a document in the last 5 minutes, with '
        + `${remaining} remaining.`,
      recommendedAction: 'check_worker_service',
      severity: 'warning',
    }
  }
  if (totalCount > 0 && completedCount >= totalCount) {
    return {
      state: 'completed',
      headline: 'Assessment complete',
      detail: `${completedCount} of ${totalCount} documents processed.`,
      recommendedAction: null,
      severity: 'info',
    }
  }
  if (processingCount > 0) {
    return {
      state: 'assessing',
      headline: currentFile ? `Assessing ${currentFile}` : 'Assessing documents',
      detail: [
        `${completedCount} of ${totalCount} completed`,
        `${processingCount} processing`,
        waitingCount > 0 ? `${waitingCount} waiting` : null,
        currentPhase || null,
      ].filter(Boolean).join(' · '),
      recommendedAction: null,
      severity: 'active',
    }
  }
  const pickupRange = pickupEstimate?.state === 'estimated' && pickupEstimate.earliest_at && pickupEstimate.latest_at
    ? fmtPickupRange(pickupEstimate.earliest_at, pickupEstimate.latest_at) : null
  return {
    state: 'waiting',
    headline: 'Waiting for a worker to pick this up',
    detail: `${waitingCount} document${waitingCount === 1 ? '' : 's'} ahead in the queue.`
      + (lastActivityMins != null ? ` Last activity ${lastActivityMins} min ago.` : '')
      + (pickupRange ? ` Estimated pickup: ${pickupRange}.` : ''),
    recommendedAction: null,
    severity: 'waiting',
    pickupUnavailable: !pickupRange,
  }
}
