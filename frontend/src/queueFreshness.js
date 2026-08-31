/**
 * Four explicit states for a polled feed, so "we have not asked yet" can never render as "there
 * is nothing there".
 *
 * THE DEFECT. QueuePanel initialised its queue data to `null` and derived everything from it with
 * a fallback:
 *
 *     const q = useState(null)
 *     const stats   = q?.stats || {}                       // {} before any response
 *     const shown   = order.filter((s) => stats[s])        // []
 *     const workers = q?.workers ?? 0                      // 0
 *
 * and then rendered `shown.length === 0 && !err` as "queue empty — nothing in flight", and
 * `{workers}` as a live count with +/- controls beside it. On first mount, before a single
 * response had arrived, that is: **queue empty, zero workers** — two confident factual claims
 * that no successful read had established. Worse, it renders identically whether the request is
 * in flight, slow, or has been failing for a minute, so an operator cannot tell "nothing is
 * queued" from "I cannot see the queue".
 *
 * `null` was doing double duty as "not asked yet" and "nothing there". These are the four states
 * it was collapsing, and they call for four different things on screen:
 *
 *   loading      no successful response has EVER arrived, and nothing has failed yet. Say so;
 *                assert nothing about the queue or the workers.
 *   current      a successful response arrived recently. Counts are live; render them plainly.
 *   stale        a successful response arrived, but is older than the feed's staleness window
 *                (jobsFeed.STALE_AFTER_MS) or a later poll has failed. The LAST-KNOWN counts are
 *                still the best information available and are worth showing — but only alongside
 *                their age, so a number from four minutes ago is never read as current.
 *   unavailable  the feed has failed and there is nothing cached to fall back on. There is no
 *                honest count to show at all.
 *
 * The distinction that matters most is `loading` vs `current`-with-nothing-queued, because both
 * have zero jobs to show and only one of them means the queue is empty.
 *
 * jobsFeed already supplies everything needed: `onData(data, meta)` and `onError(err, meta)` both
 * carry `{ fetchedAt, ageMs, stale }`. This module only decides what those add up to; it does no
 * fetching of its own, which is what makes it testable without a network or a timer.
 */

/** Every state a polled feed can be in. Exported so a test can assert the set is exhaustive. */
export const FEED_STATES = ['loading', 'current', 'stale', 'unavailable']

/**
 * @param {object}  o
 * @param {*}       o.data   the last successful payload, or null/undefined if there has never been one
 * @param {object}  o.meta   jobsFeed's `{ fetchedAt, ageMs, stale }`, if any
 * @param {*}       o.error  a truthy error from the most recent poll, if it failed
 * @returns {'loading'|'current'|'stale'|'unavailable'}
 */
export function deriveFeedState({ data, meta, error } = {}) {
  const everSucceeded = data !== null && data !== undefined
  if (!everSucceeded) return error ? 'unavailable' : 'loading'
  // Cached data plus a failing poll is exactly the case worth distinguishing: the counts are real,
  // they are simply old. Showing them WITH their age beats both blanking the panel and pretending
  // they are live.
  if (error) return 'stale'
  return meta && meta.stale ? 'stale' : 'current'
}

/**
 * May the UI make a positive claim about the queue's contents — "empty", a count, a worker
 * number? Only once a successful response has actually confirmed it.
 *
 * `stale` qualifies deliberately: a real response DID establish those numbers, and the caller is
 * required to render the age beside them (see ageLabel). `loading` and `unavailable` never do —
 * nothing has confirmed anything.
 */
export function hasConfirmedData(state) {
  return state === 'current' || state === 'stale'
}

/** Should the freshness/age line be shown? Only when the data is real but not fresh. */
export function needsFreshnessLabel(state) {
  return state === 'stale'
}

/**
 * Human age for a last-known reading. Deliberately coarse — the point is "how out of date is
 * this", not a stopwatch, and a number that ticks every second invites reading it as live.
 *
 * Returns null when there is no timestamp, so the caller renders nothing rather than "unknown
 * ago" or a fabricated zero.
 */
export function ageLabel(ageMs) {
  if (ageMs === null || ageMs === undefined || !Number.isFinite(ageMs) || ageMs < 0) return null
  const s = Math.round(ageMs / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  return `${h}h ago`
}

/**
 * One sentence for the state, for a panel that has no counts to show.
 * Never claims anything about the queue's contents.
 */
export function statusLine(state, { ageMs } = {}) {
  if (state === 'loading') return 'checking the queue…'
  if (state === 'unavailable') return 'queue unavailable — could not read it'
  if (state === 'stale') {
    const age = ageLabel(ageMs)
    return age ? `last known ${age} — not confirmed since` : 'last known reading — not confirmed since'
  }
  return null
}

/**
 * Is the runtime topology known? Worker controls must not be offered when it is not.
 *
 * Distinct from the feed state on purpose: a feed can be `current` and still not say what
 * topology it is (an older API build, or a payload without the field). "Zero workers" and
 * "we do not know how this deployment runs workers" are different facts, and only one of them
 * justifies putting a +/- control in front of someone.
 */
export function topologyIsKnown(data) {
  return !!(data && typeof data.runtime_mode === 'string' && data.runtime_mode.length > 0)
}
