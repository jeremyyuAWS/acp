// Rejoining a run the browser has no memory of.
//
// THE GAP THIS CLOSES. Sign out (or "switch account") is a deliberate total wipe: App.jsx runs
// clearActivityStorage() — every `acp-` sessionStorage key — then sessionStorage.clear() and a hard
// reload, so "no scan, decisions, assess phase, or files survive". That is correct for privacy and
// wrong for in-flight work, because the jobs do not stop: the queue is durable and server-side.
//
// Discovery already reconnects from the server (GET /scans/active → store.active_scan, built for
// exactly this). Assess and Remediate did not: their cards resumed ONLY from sessionStorage, so
// signing out and back in left a running batch with no card at all — work in flight, nothing on
// screen, and no way to tell that from "it finished" or "it never started".
//
// These derive the resume decision from the server's own live snapshot. Pure, because the wiring
// they feed lives in two large components: the interesting cases (a finished run, a batch of
// unknown size, a snapshot from a backend that predates a field) are all shapes of an argument, and
// belong in a test that can simply pass that shape.

// Number, floored at zero — a count that arrives null, undefined, negative or unparseable is zero
// work. `Math.max(0, Number(x))` is NOT enough and the difference is the whole point: Number('oops')
// is NaN and Math.max(0, NaN) is NaN, which would reach a denominator and render the progress bar
// as complete. Number.isFinite is the check that actually holds.
const count = (value) => {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : 0
}

/**
 * Resume state for the remediation card from GET /scans/{sid}/remediation-status,
 * or null when there is nothing in flight to rejoin.
 *
 * `total` prefers `batch_documents` — the size of the batch the server scoped its own counts to
 * (added with the batch-scoping fix) — and falls back to the in-flight count so a snapshot from a
 * backend without that field still resumes, with a denominator that is honest about being a floor
 * rather than a guess at the batch size.
 */
export function remediationResume(status) {
  const inFlight = count(status?.in_flight)
  if (!inFlight) return null
  const total = Math.max(inFlight, count(status?.batch_documents))
  return {
    total,
    done: Math.max(0, total - inFlight),
    // Clamped like every other failure count that reaches this UI: a batch of N cannot fail more
    // than N times, and the summary subtracts.
    failed: Math.min(total, count(status?.failed)),
    latest: status?.latest_file || null,
  }
}

/**
 * Resume state for the Assess running screen from GET /scans/{sid}/live, or null.
 *
 * `available` is the snapshot's own "I know this scan" flag (an unknown or foreign scan returns
 * {available: false} rather than erroring), and `active` is its run-state predicate — both are the
 * server's judgement, not a re-derivation here, so the card cannot disagree with the run.
 */
export function assessResume(snapshot) {
  if (!snapshot?.available || !snapshot?.active) return null
  const eligible = count(snapshot?.totals?.eligible)
  const completed = count(snapshot?.kpis?.completed)
  return {
    total: eligible,
    done: Math.min(completed, eligible || completed),
    phase: snapshot.phase || 'assessing',
  }
}
