// The "scan failed: …" banner (App.jsx's `.err` div) was found live 2026-08-29 reading "scan
// failed: 500" — the raw HTTP status code, with nothing describing what happened or what to do.
//
// api.js's `j()` throws `${status} ${statusText}` when a non-OK response carries no JSON `detail`
// body — and browsers routinely report an empty `statusText` for HTTP/2 responses, so that
// fallback often surfaces as a bare, unexplained number. Every OTHER error thrown into doScan's
// or reconnectJob's catch is a purpose-written phrase for a person to read (SCAN_UNAVAILABLE, "no
// workers available — …", "can't start this scan — …", "this scan never started — …", …) — none
// of them start with three digits, so a leading 3-digit code is a precise, not a guessed, signal
// that this is the generic HTTP fallback rather than a message anyone actually wrote.
const BARE_STATUS = /^(\d{3})\b/

/**
 * @param rawMessage  e?.message ?? e from the catch block.
 * @returns a message safe to show as the primary line of the failure banner — the original
 *          purpose-written message unchanged, or a plain-language stand-in (with the code kept,
 *          parenthetically, for anyone who needs it) when the only thing available was a bare
 *          HTTP status.
 */
export function scanFailureDetail(rawMessage) {
  const trimmed = String(rawMessage ?? '').trim()
  const m = BARE_STATUS.exec(trimmed)
  if (!m) return trimmed
  return `the server had a problem processing this (HTTP ${m[1]}) — this is usually temporary; try again in a moment`
}

/**
 * Whether the failure banner needs to say a previous inventory is still shown below it.
 *
 * Discover.jsx never clears `scan` on a failed re-attempt — `setScan(fresh)` only runs after a
 * NEW scan succeeds (App.jsx's doScan/reconnectJob), so a failed attempt leaves the previous
 * scan's own completed results on screen exactly as they were. Found live 2026-08-29: a "scan
 * failed: 500" banner rendered directly above a "Discovery complete" card from the last good run,
 * with nothing on screen explaining that the two describe different attempts.
 *
 * Takes BOTH `discovered_at` and `completed_at` — checking `completed_at` alone (the original
 * shape of this function) went false-negative on a Discover-only run under ADR 0020's phase
 * separation: `completed_at` is set only once the whole pipeline (through Assess) finishes, but
 * Discover.jsx's own completion card renders off `discovered_at`/`status==='discovered'` (see its
 * "Discovery complete" block) well before that. Found live 2026-08-30: a completion card showing
 * 6,922 real files sat under a "scan failed" banner with the reassurance line silently missing,
 * because the run behind it was discovered-but-not-yet-assessed — `discovered_at` was real,
 * `completed_at` was still null.
 *
 * @param discoveredAt  scan?.run?.discovered_at
 * @param completedAt   scan?.run?.completed_at
 */
export function hasFallbackInventory(discoveredAt, completedAt) {
  return !!(discoveredAt || completedAt)
}
