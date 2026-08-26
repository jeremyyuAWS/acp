// Pure decision logic for POST /discovery/preflight's response, kept out of App.jsx's doScan so
// it is unit-testable on its own — the same reasoning as scanPollDecision.js/fallbackPollBackoff.js:
// logic embedded directly in doScan has no test reachable from anywhere, which is how branches go
// unexercised for a long time.
//
// Only a 'blocked' verdict stops a scan from starting. 'degraded' (e.g. a queue backlog) is
// allowed through — but unlike a blocked scan, which never starts and so needs no further trace,
// a degraded one DOES start, and the reason it was degraded is worth showing on the run itself
// (DiscoverRunProgress) rather than disappearing the instant the check passes. This one function
// is the single source of truth for both: the blocking decision AND the banner content, so the
// two can never read the response differently.
export function preflightVerdict(pre) {
  if (!pre || pre.verdict === 'ready') return { blocked: false, reason: null, degradedReasons: [] }
  if (pre.verdict === 'blocked') {
    const reason = (pre.blocked_reasons || [])[0] || 'this source is not currently reachable'
    return { blocked: true, reason, degradedReasons: [] }
  }
  // 'degraded' (or an unrecognized future verdict — fail open, never block on an unknown value).
  return { blocked: false, reason: null, degradedReasons: pre.degraded_reasons || [] }
}
