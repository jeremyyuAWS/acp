// Reviewer time — MEASURED, from hitl_events.review_ms (client-clocked from card-open to
// decision), aggregated by store.hitl_analytics.
//
// This replaces "est. savings 12.4 hrs", which was not a measurement of anything. It came from
// sim.js recommendFor: manualMin = findings × 35 + 20, remediateMin = findings × ~1, and
// savedMin = the difference. Nobody ever timed a document being remediated by hand, so the
// "saving" was one invented constant subtracted from another, printed as a headline.
//
// A SAVING needs a counterfactual — how long the same work would have taken without ACP — and
// we have never measured that. What we can honestly report is how long reviews actually take
// and how many findings were fixed with no human at all. So we report those, and nothing else.

export const REVIEW_TIME_BASIS =
  'Measured: median of the time from opening a review card to deciding it (hitl_events.review_ms).'

// ms → "8s" / "1m 24s". Null for anything unmeasured, so the caller renders nothing.
export function fmtReviewMs(ms) {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms <= 0) return null
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

// The only reviewer-time claim this product is allowed to make: an average over decisions that
// actually happened. Returns null until at least one review has been recorded — a single data
// point is a number, not a statistic, so require a couple before showing an average.
export function measuredReviewTime(analytics, { minSamples = 2 } = {}) {
  const n = analytics?.timed_reviews
  const median = fmtReviewMs(analytics?.median_review_ms)
  if (!median || typeof n !== 'number' || n < minSamples) return null
  return { median, reviewed: n, basis: REVIEW_TIME_BASIS }
}

export function reviewTimeImpact(cardDelta, analytics, options) {
  const measured = measuredReviewTime(analytics, options)
  if (!measured || !Number.isFinite(cardDelta)) return null
  return { ...measured, deltaMs: cardDelta * analytics.median_review_ms,
    delta: fmtReviewMs(Math.abs(cardDelta * analytics.median_review_ms)), direction: Math.sign(cardDelta) }
}
