// Pure decision logic for POST /discovery/preflight's response, kept out of App.jsx's doScan so
// it is unit-testable on its own — the same reasoning as scanPollDecision.js/fallbackPollBackoff.js:
// logic embedded directly in doScan has no test reachable from anywhere, which is how branches go
// unexercised for a long time.
//
// Only a 'blocked' verdict stops a scan from starting. 'degraded' (e.g. "starting" — no workers
// right now but the durable queue can accept the scan) is allowed through.
//
// capacityState maps to the UI treatment:
//   "ready"       — nothing to show
//   "starting"    — blue notice: "Preparing Discovery capacity"
//   "busy"        — blue notice: scan will be queued behind backlog
//   "degraded"    — amber warning
//   "unavailable" — red, scan blocked (worker tier never started)
//   "unknown"     — no data yet (probe failed or not returned)
export function preflightVerdict(pre) {
  const capacityState = pre?.capacity_state ?? 'unknown'

  if (!pre || pre.verdict === 'ready') {
    return { blocked: false, reason: null, capacityState, degradedReasons: [] }
  }
  if (pre.verdict === 'blocked') {
    const reason = (pre.blocked_reasons || [])[0] || 'this source is not currently reachable'
    return { blocked: true, reason, capacityState, degradedReasons: [] }
  }
  // 'degraded' (or an unrecognized future verdict — fail open, never block on an unknown value).
  return { blocked: false, reason: null, capacityState, degradedReasons: pre.degraded_reasons || [] }
}
