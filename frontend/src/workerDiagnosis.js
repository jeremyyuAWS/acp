// A diagnosis layer: turns the raw worker/Azure signals this app already collects (heartbeat
// age, queue-stall, replica config, capacity evidence, revision health) into a single ranked
// "here's likely why" explanation — instead of a person having to correlate several separately
//-shown facts (WorkerAvailability.jsx, QueuePanel.jsx) themselves every time something looks
// off. Pure function, no fetching: callers pass in the same `snap`/`capacity`/`replicas` shapes
// those components already receive.
//
// Rules are checked in priority order — most specific/actionable first — and the first true
// rule wins. Stacking every applicable message would just be a second wall of facts to triage;
// one clear, ranked answer is the point of a diagnosis layer.

import { isQueueStalled, queuedAgeSecs } from './workerStallSignal.js'

// store.py's worker_tier_status() computes `alive = age_s <= 120`. An age past HALF that window
// while still technically "alive" is the worker falling behind its own heartbeat cadence — worth
// a warning before the binary flag flips to offline, not just after.
const HEARTBEAT_AGING_THRESHOLD_S = 60

// Round-number threshold for "loaded enough that more replicas or a bigger SKU is worth
// considering" — deliberately not exact tuning, just the point past which "fine" stops being the
// obvious read of the number. Exported so UtilizationBar.jsx's color bands agree with this rule
// about what counts as "hot" — the bar and the diagnosis text must never disagree.
export const HIGH_UTILIZATION_PCT = 80

/** Returns `{ severity: 'warning'|'critical', message: string }` for the single most actionable
 *  problem, or `null` when nothing in the passed-in signals looks wrong. `snap` is the GET /jobs-
 *  derived shape (workers, alive, runtime_mode, oldestQueuedCreatedAt, workerHeartbeatAgeS);
 *  `capacity` and `replicas` are GET /control/workers/capacity and .../replicas respectively —
 *  both optional, since only the distributed (Azure) runtime mode has them. */
export function diagnoseWorkerHealth({ snap, capacity, replicas, nowMs = Date.now() } = {}) {
  if (!snap) return null

  // 1. Offline, and never once reported in — the worker tier likely never started.
  if (!snap.alive && snap.workerHeartbeatAgeS == null) {
    return { severity: 'critical',
      message: 'No worker has ever reported in — the worker tier may never have started.' }
  }

  // 2. Offline, Azure-managed, and Azure itself shows zero replicas running — point at the more
  //    specific cause rather than the generic "offline" a person already sees from the dot.
  if (!snap.alive && snap.runtime_mode === 'distributed'
      && capacity?.configured && capacity.current_replicas === 0) {
    return { severity: 'critical',
      message: 'Azure shows 0 replicas running — the container app may be failing to start. Check Container App logs.' }
  }

  // 3. Offline, generic — it beat before but has gone stale past the 120s alive window.
  if (!snap.alive && snap.workerHeartbeatAgeS != null) {
    return { severity: 'critical',
      message: `The worker tier hasn't reported in for ${Math.round(snap.workerHeartbeatAgeS)}s — it likely crashed or was stopped.` }
  }

  // From here on the tier is alive. Azure-specific signals next, since they're the most
  // concrete/actionable when present.
  if (capacity?.configured) {
    if (capacity.revision_health === 'Unhealthy') {
      return { severity: 'critical',
        message: 'The active Container App revision is reporting Unhealthy — a recent deploy may have failed to start cleanly. Check Container App revision logs.' }
    }
    if (capacity.revision_provisioning_state === 'Failed') {
      return { severity: 'critical',
        message: 'The active revision failed to provision — the last deploy likely did not complete. Check Container App deployment logs.' }
    }
    if (replicas?.configured && replicas.min_replicas > 0 && capacity.current_replicas === 0) {
      return { severity: 'critical',
        message: `Azure is configured to keep ${replicas.min_replicas} replica${replicas.min_replicas === 1 ? '' : 's'} warm, but none are currently running — the container app may be failing to start. Check Container App logs and the identity's Azure permissions.` }
    }
    // A revision can be perfectly Healthy, Provisioned, and running replicas while still
    // receiving 0% of ingress traffic — a real incident on this app: a stuck blue-green rollout
    // left the new revision healthy but unreachable, and nothing surfaced it until customer
    // requests kept hitting the old one. current_replicas > 0 distinguishes "genuinely stranded"
    // from the zero-replicas case above, which is a different, already-caught problem.
    if (capacity.revision_traffic_percent === 0 && (capacity.current_replicas ?? 0) > 0) {
      return { severity: 'critical',
        message: 'The active revision is running but receiving 0% of ingress traffic — check whether a rollout is stuck mid-cutover in the Azure portal.' }
    }
  }

  // 4. Heartbeat aging toward the alive threshold — an early warning before it flips offline.
  if (snap.workerHeartbeatAgeS != null && snap.workerHeartbeatAgeS >= HEARTBEAT_AGING_THRESHOLD_S) {
    return { severity: 'warning',
      message: `Worker heartbeat is ${Math.round(snap.workerHeartbeatAgeS)}s old and getting close to the alive threshold — the worker may be overloaded or about to go offline.` }
  }

  // 5. Reports online, but the oldest queued job has waited past the stall threshold — the
  //    tier's heartbeat proves the container is up, not that anything is actually claiming work.
  if (isQueueStalled(snap.alive, snap.oldestQueuedCreatedAt, nowMs)) {
    const age = queuedAgeSecs(snap.oldestQueuedCreatedAt, nowMs)
    return { severity: 'warning',
      message: `Workers report online, but a queued job has waited ${age}s — it may not be actually claiming work. Check the worker process or job routing.` }
  }

  // 6. Everything above is fine, but capacity is genuinely stretched: at the configured ceiling
  //    and running hot. This is the concrete "should we upgrade" signal, not a guess.
  if (capacity?.configured && capacity.metrics_available
      && capacity.current_replicas != null && replicas?.max_replicas != null
      && capacity.current_replicas >= replicas.max_replicas
      && ((capacity.cpu_percent ?? 0) >= HIGH_UTILIZATION_PCT
          || (capacity.memory_percent ?? 0) >= HIGH_UTILIZATION_PCT)) {
    const pct = Math.max(capacity.cpu_percent ?? 0, capacity.memory_percent ?? 0)
    return { severity: 'warning',
      message: `Running at the configured max (${replicas.max_replicas}) replicas with ${pct}% utilization — consider raising max replicas or the per-replica size.` }
  }

  // 7. Low-priority/informational only: CPU/Memory metrics are missing specifically because the
  //    Monitor Reader call was denied, not because there's simply no data yet (which is normal
  //    right after a cold start) or a transient error. Deliberately not raised for those other two
  //    reasons — this is the one case that won't self-resolve without an RBAC change.
  if (capacity?.configured && capacity.metrics_unavailable_reason === 'permission') {
    return { severity: 'warning',
      message: 'Azure Monitor metrics are unavailable — the app identity may be missing the Monitoring Reader role on the Container App.' }
  }

  return null
}
