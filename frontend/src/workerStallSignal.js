// A worker heartbeat proves the container is up, not that anything is actually claiming work —
// see worker.py's own max_unverified_lease_s docstring, and the two live bugs (#935/#936) that
// produced exactly that gap on 2026-08-29: a worker pool that silently booted at zero threads,
// and a Drive HTTP client with no socket timeout that could hang a claimed job forever. Both
// looked identical to "online" from the heartbeat alone.
//
// The oldest queued job's own age (GET /jobs's `oldest_queued.created_at`, api/store.py's
// oldest_queued_job) is a fact the worker tier can't fake by merely existing — this decides when
// that age is worth telling a person about.
//
// 90s matches DiscoverRunProgress.jsx's own "Discovery appears stalled" threshold — one stall
// vocabulary across the app, not two.
export const STALL_THRESHOLD_S = 90

/** Seconds since `createdAt` (an ISO timestamp), or null when there's nothing queued / the
 *  timestamp doesn't parse. Never negative — a small clock skew must not read as a job queued in
 *  the future. */
export function queuedAgeSecs(createdAt, nowMs = Date.now()) {
  if (!createdAt) return null
  const ageMs = nowMs - Date.parse(createdAt)
  return Number.isFinite(ageMs) ? Math.max(0, Math.round(ageMs / 1000)) : null
}

/** Whether the worker tier looks stuck: it reports alive, yet the oldest queued job has waited
 *  past the stall threshold. False whenever the tier is offline — that is a different, already
 *  visible problem ("Worker service offline"), not this one. */
export function isQueueStalled(alive, createdAt, nowMs = Date.now()) {
  if (!alive) return false
  const age = queuedAgeSecs(createdAt, nowMs)
  return age != null && age >= STALL_THRESHOLD_S
}
