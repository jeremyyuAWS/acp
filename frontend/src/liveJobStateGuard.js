// Out-of-order / stale-attempt protection for the live SSE job-state ref (App.jsx's
// liveJobStateRef, fed by openDiscoverStream's onMessage). The stream is a snapshot-REPLACE, not
// an event log — each `data:` frame is the job's full current state, not a delta — so within one
// SSE connection TCP already guarantees in-order delivery; there is nothing to reorder there.
//
// The real race is between the fallback getJob() poll (App.jsx's doScan/reconnectScan loops,
// used once sseFailedRef trips) and a late-arriving SSE frame from before the fallback kicked
// in — the two update the same liveJobStateRef from different code paths with no ordering
// guarantee between them. Backend seq (api/core.py's update_job, HINCRBY per write) and attempt
// (job["attempts"], api/handlers.py's _scan_discover) give the client enough to detect and drop
// a stale write instead of letting it silently regress the card (PRD §11: "out-of-order events
// do not regress the card").
//
// attempt takes priority over seq: seq is scoped to ONE job attempt (it is not reset on the
// current in-place retry model, but a future retry path that DOES mint a new job_id would reset
// it — see api/routes/scans.py's discover/stream docstring), so a higher attempt always wins
// regardless of what its seq says, and a lower attempt is always stale regardless of its seq.

/** Should `next` replace `prev` as the live job state? True when there is nothing to compare
 *  against, or when `next` is not demonstrably older than `prev`. */
export function acceptLiveJobState(prev, next) {
  if (!next) return false
  if (!prev) return true

  const prevAttempt = prev.attempt
  const nextAttempt = next.attempt
  if (typeof prevAttempt === 'number' && typeof nextAttempt === 'number' && prevAttempt !== nextAttempt) {
    return nextAttempt > prevAttempt
  }

  const prevSeq = prev.seq
  const nextSeq = next.seq
  if (typeof prevSeq === 'number' && typeof nextSeq === 'number' && nextSeq < prevSeq) return false

  return true
}
