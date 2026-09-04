// The human-readable reason a discovery run ended in status='failed', from its decision log.
//
// api/handlers.py's _scan_discover logs one of a small set of scan-level decisions immediately
// around calling set_scan_status(scan_id, 'failed') — each with a specific, actionable `detail`
// string: a single-flight conflict ("Discovery already active for source 'drive': scan X is
// still running"), a listing exception, a suspicious zero (fewer files than a proven baseline),
// or an unreachable-source zero. The Discover tab's failed banner never read any of them; it
// always showed the same generic "the last attempt to list this source failed" regardless of
// which of these it was — so a benign, expected rejection (another scan of this source is
// already running) read exactly like a genuinely broken one (an expired token, a dead API).
//
// Deliberately an allowlist, not a `scan.` prefix match: other scan.* kinds (scan.discovered,
// scan.file_error, scan.drive_unusable, …) are not failure reasons for THIS run's status, and
// matching by prefix would surface an unrelated per-file or bookkeeping entry as if it explained
// why the whole scan failed.
const FAILURE_KINDS = new Set([
  'scan.discover_conflict',
  'scan.discover_failed',
  'scan.suspicious_zero',
  'scan.unreachable_zero',
  'scan.scope_collapse',
])

/**
 * @param decisions  GET /decisions?scan_id=… rows, most-recent-first (list_decisions orders by
 *                   ts DESC) — the same array Discover.jsx already loads into `errLog`.
 * @returns the most recent matching decision's `detail`, or null when none was recorded (e.g. a
 *          transient DB error on the suspicious-zero check logs no decision at all) — the caller
 *          falls back to a generic message rather than fabricating one.
 */
export function discoveryFailureReason(decisions) {
  if (!Array.isArray(decisions)) return null
  const row = decisions.find((d) => d && !d.file && FAILURE_KINDS.has(d.action))
  return row?.detail || null
}
