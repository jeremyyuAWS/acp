// One GET /jobs subscription per equivalent query, shared by every component that wants it.
//
// PRD "Automatic Worker Provisioning" §8: "Share job-status subscriptions across components.
// Avoid separate polling loops for the same information."
//
// The cost is measured, not assumed. Against the real route, ONE GET /jobs costs 5 connection-pool
// acquisitions and 6 queries — worker heartbeat, oldest queued job, job stats, dead-letter
// breakdown, job list, each its own cursor(). Five components poll it on private timers
// (Discover twice), so a Discover tick alone was 10 acquisitions. During the 2026-08-30
// pool-exhaustion incident /jobs was the single most-failed route: 36 of the 90 HTTP 500s.
//
// ── Cache key: endpoint + identity + query ────────────────────────────────────────────────────
// /jobs is OWNER-SCOPED server-side — stats, job list and dead-letters are all filtered to the
// caller — so a cached response belongs to the account that fetched it. The key carries
// api.js's `authEpoch()`, a non-secret stamp that changes on sign-in, sign-out and account
// switch (never the bearer token itself: a credential does not belong in a cache key). On a
// switch the key stops matching AND the old entries are dropped, so one account's queue can
// never be handed to the next.
//
// Keyed by the STATUS FILTER because that is what changes the response. Everything else /jobs
// returns — workers, worker_tier_alive, worker_heartbeat_age_s, suggested_workers, runtime_mode,
// oldest_queued, stats, dead_letters — is identical whatever the filter is, which is why
// Discover's queued-filtered effect already reads `workers` off it. Only `jobs` differs.
//
// Deliberately NOT done: deriving the queued list from an unfiltered response. That call is
// capped (limit=100 server-side), so a busy queue would silently truncate and a component
// counting "jobs ahead of me" would under-report. The PRD names this trap directly. Distinct
// filters stay distinct requests; the sharing happens among callers wanting the SAME one.
//
// ── Freshness: stale-while-revalidate, honestly labelled ──────────────────────────────────────
// A subscriber mounting onto a warm cache is handed the cached payload IMMEDIATELY, together
// with the real `fetchedAt` of the fetch that produced it and a `stale` flag — never a fresh
// timestamp. Mounting must not make old data look new. A revalidation is kicked off in the same
// breath whenever the cache is older than the subscriber's own interval, so "shown instantly"
// and "known to be current" stay separate claims.

import { getJobs } from './api.js'
import { authEpoch, apiBase } from './apiIdentity.js'

const feeds = new Map()
const DEFAULT_INTERVAL = 10000
const MAX_BACKOFF = 60000

/** Older than this and a cached payload is handed over flagged `stale: true`. */
export const STALE_AFTER_MS = 30000

const keyFor = (status) => `${apiBase()}|${authEpoch()}|${status ?? ''}`

function makeFeed(key, status, epoch) {
  return {
    key,
    status,
    epoch,
    subs: new Set(),
    timer: null,
    inFlight: null,      // the shared promise; equivalent subscribers attach rather than refetch
    generation: 0,       // bumped by reset/teardown — a response from an older one is discarded
    last: null,          // { data, fetchedAt } — fetchedAt is the REAL time of the fetch
    failures: 0,
  }
}

const metaFor = (feed) => {
  const at = feed.last ? feed.last.fetchedAt : null
  const age = at === null ? null : Date.now() - at
  return { fetchedAt: at, ageMs: age, stale: age === null ? true : age > STALE_AFTER_MS }
}

function tickFor(feed) {
  let ms = Infinity
  for (const s of feed.subs) ms = Math.min(ms, s.intervalMs || DEFAULT_INTERVAL)
  return Number.isFinite(ms) ? ms : DEFAULT_INTERVAL
}

/** Backoff after failures, jittered so N tabs recovering do not retry in lockstep. */
function delayFor(feed) {
  const base = tickFor(feed)
  if (!feed.failures) return base
  return Math.min(base * 2 ** feed.failures, MAX_BACKOFF) * (0.5 + Math.random() * 0.5)
}

function schedule(feed) {
  clearTimeout(feed.timer)
  feed.timer = null
  if (!feed.subs.size) return
  if (typeof document !== 'undefined' && document.hidden) return   // paused; visibility resumes
  feed.timer = setTimeout(() => { poll(feed) }, delayFor(feed))
}

function emit(feed, err) {
  const meta = metaFor(feed)
  for (const s of [...feed.subs]) {
    try {
      if (err) s.onError?.(err, meta)
      else if (feed.last) s.onData(feed.last.data, meta)
    } catch { /* a subscriber's own failure is not this module's to handle */ }
  }
}

/**
 * Fetch once for the whole feed. Concurrent callers attach to the in-flight promise rather than
 * issuing a second request — the "avoid overlapping polling" requirement, enforced here rather
 * than left to each caller's timer.
 */
function poll(feed) {
  if (!feed.subs.size) return Promise.resolve()
  if (typeof document !== 'undefined' && document.hidden) return Promise.resolve()
  if (feed.inFlight) return feed.inFlight

  const gen = feed.generation
  const p = getJobs(feed.status).then((data) => {
    // A response that outlived its generation belongs to a torn-down or signed-out feed. It must
    // not repopulate a cleared cache, and it must never overwrite a NEWER session's data. There
    // is no fetch abort available through api.js, so the response is discarded on arrival — the
    // same guarantee, one round trip later.
    if (gen !== feed.generation) return
    feed.inFlight = null
    feed.failures = 0
    feed.last = { data, fetchedAt: Date.now() }
    emit(feed)
    schedule(feed)
  }).catch((err) => {
    if (gen !== feed.generation) return
    feed.inFlight = null
    feed.failures += 1
    // The last known payload is deliberately KEPT, with its real timestamp: the PRD asks for
    // last-known-plus-freshness, not a blank. Subscribers get the error and the age together and
    // can say "unavailable, last seen 40s ago" rather than showing a stale number as current.
    emit(feed, err)
    schedule(feed)
  })
  feed.inFlight = p
  return p
}

/**
 * Subscribe to GET /jobs for one status filter.
 *
 * `onData(data, meta)` — meta is `{ fetchedAt, ageMs, stale }`. Existing callers that take only
 * `data` keep working. `onError(err, meta)` fires on a failed poll, with the age of whatever is
 * still cached.
 *
 * Returns an unsubscribe function. Polling stops when the last subscriber leaves.
 */
export function subscribeJobs(status, onData, { intervalMs = DEFAULT_INTERVAL, onError } = {}) {
  const key = keyFor(status)
  let feed = feeds.get(key)
  if (!feed) {
    // A new identity means every other identity's cache is now unreachable AND unwanted. Drop it
    // rather than leaving another account's queue sitting in memory until the tab closes.
    const epoch = authEpoch()
    for (const [k, f] of [...feeds]) {
      if (f.epoch !== epoch) { clearTimeout(f.timer); f.generation += 1; feeds.delete(k) }
    }
    feed = makeFeed(key, status ?? null, epoch)
    feeds.set(key, feed)
  }
  const sub = { onData, onError, intervalMs }
  feed.subs.add(sub)

  // Stale-while-revalidate: hand over what we have, labelled with its REAL age, then refresh if
  // it is older than this subscriber is willing to accept.
  if (feed.last) { try { onData(feed.last.data, metaFor(feed)) } catch { /* ignore */ } }
  const age = feed.last ? Date.now() - feed.last.fetchedAt : Infinity
  if (age >= intervalMs) poll(feed)
  else schedule(feed)

  return () => {
    feed.subs.delete(sub)
    if (!feed.subs.size) {
      clearTimeout(feed.timer)
      feed.timer = null
      // Stop polling, and invalidate anything outstanding so a late response cannot repopulate
      // this feed after teardown. The CACHE IS KEPT, with its timestamp: a remount seconds later
      // should not have to re-fetch to draw, and the `stale` flag stops it being mistaken for
      // fresh. Identity change and explicit reset are what drop it — not an unmount.
      feed.generation += 1
      feed.inFlight = null
    }
  }
}

/**
 * Drop every cached response, stop every timer, and invalidate every outstanding request.
 * Wired to sign-out below; call it directly from a test's cleanup.
 */
export function resetJobsFeed() {
  for (const feed of feeds.values()) {
    clearTimeout(feed.timer)
    feed.timer = null
    feed.generation += 1
    feed.inFlight = null
  }
  feeds.clear()
}

/** Test seam: what the module holds right now. */
export function _feedState() {
  return [...feeds.values()].map((f) => ({
    key: f.key, subs: f.subs.size, polling: f.timer !== null,
    hasCache: !!f.last, fetchedAt: f.last ? f.last.fetchedAt : null,
  }))
}

if (typeof window !== 'undefined') {
  window.addEventListener('acp:session-expired', resetJobsFeed)
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('visibilitychange', () => {
      for (const feed of feeds.values()) {
        if (document.hidden) { clearTimeout(feed.timer); feed.timer = null }
        else if (feed.subs.size) poll(feed)      // catch up on return, then resume the cadence
      }
    })
  }
}
