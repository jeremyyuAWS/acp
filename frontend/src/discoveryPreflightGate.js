// Pure decision logic for POST /discovery/preflight's response, kept out of App.jsx's doScan so
// it is unit-testable on its own — the same reasoning as scanPollDecision.js/fallbackPollBackoff.js:
// logic embedded directly in doScan has no test reachable from anywhere, which is how branches go
// unexercised for a long time.
//
// Only a 'blocked' verdict stops a scan from starting. 'degraded' (e.g. a queue backlog) is
// allowed through — the existing readyz banner already covers ambient, non-blocking warnings; this
// gate exists specifically for what would otherwise fail or silently return nothing.
export function preflightVerdict(pre) {
  if (!pre || pre.verdict !== 'blocked') return { blocked: false, reason: null }
  const reason = (pre.blocked_reasons || [])[0] || 'this source is not currently reachable'
  return { blocked: true, reason }
}
