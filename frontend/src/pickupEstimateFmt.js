// "2–4 min" from a queue-estimate route response's earliest_at/latest_at (ISO timestamps,
// absolute — so this stays correct across however long the fact sits on screen before its next
// poll, unlike a range computed once at fetch time and left to go stale). Shared by every
// Processing status panel's own derive-state module (Discover, Assess, Remediate) — one
// formatting rule, not a copy per tab that can drift.
export function fmtPickupRange(earliestAt, latestAt) {
  const now = Date.now()
  const lo = Math.max(0, Math.round((Date.parse(earliestAt) - now) / 60000))
  const hi = Math.max(lo, Math.round((Date.parse(latestAt) - now) / 60000))
  if (hi === 0) return 'under a minute'
  return lo === hi ? `about ${hi} min` : `${lo}–${hi} min`
}
