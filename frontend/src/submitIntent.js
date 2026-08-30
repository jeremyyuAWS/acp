// One idempotency key per SUBMIT INTENT, retained across retries of that intent.
//
// PRD "Automatic Worker Provisioning", §4.A: "Support owner-scoped idempotency keys for retried
// requests" and "Provide a way to reconcile an uncertain submission after a timeout". The server
// half has worked for some time — enqueue_scan honours an Idempotency-Key header and returns the
// ORIGINAL (scan_id, job_id) rather than inserting a duplicate — but nothing in the client ever
// sent one, so the guarantee was unreachable from the product.
//
// The unit of identity is the INTENT, not the request parameters. Keying on "source + folders +
// options" would look tidy and would break Re-scan: two deliberate runs of the same scope would
// collide, and the second would silently hand back the first run's scan instead of starting a new
// one. So a key is minted when a submit intent OPENS and lives until that intent RESOLVES:
//
//   accepted        -> complete()  : the job is durable; the next click is a new intent
//   confirmed no-op -> abandon()   : the server proved nothing was created (a 4xx); same
//   uncertain       -> keep it     : a timeout, a dropped connection, a 503. The next attempt
//                                    REUSES the key, so if the earlier request did commit before
//                                    the response was lost, the server returns that job instead
//                                    of creating a second one.
//
// That last line is the whole point, and it is why nothing here mints a fresh key on failure.
//
// Storage is sessionStorage so an intent survives the reload that a mid-submit crash or an
// impatient refresh produces — exactly the window where a duplicate would otherwise be created.
// Every access is guarded: Safari private mode and "block site data" make sessionStorage throw on
// read AND write, and a submit path must not break because storage is unavailable, so an
// in-memory map backs it up. That fallback is per-tab and does not survive a reload, which is a
// degradation of the reconcile guarantee, not of correctness — the server-side check still holds
// for as long as the key does reach it.

const PREFIX = 'acp.submitIntent.'
const memory = new Map()

function readStored(scope) {
  try {
    const v = sessionStorage.getItem(PREFIX + scope)
    if (v) return v
  } catch { /* storage unavailable — fall through to memory */ }
  return memory.get(scope) || null
}

function writeStored(scope, key) {
  memory.set(scope, key)
  try { sessionStorage.setItem(PREFIX + scope, key) } catch { /* memory already holds it */ }
}

function dropStored(scope) {
  memory.delete(scope)
  try { sessionStorage.removeItem(PREFIX + scope) } catch { /* nothing else to do */ }
}

/** A key unique enough to be an identity, from whatever the browser offers. */
function mint() {
  try {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  } catch { /* fall through */ }
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

/**
 * The key for `scope`'s current submit intent, minting one if no intent is open.
 * Call this on EVERY attempt: a retry gets the same key back, which is what makes the retry safe.
 */
export function beginOrResumeIntent(scope = 'scan') {
  const existing = readStored(scope)
  if (existing) return existing
  const key = mint()
  writeStored(scope, key)
  return key
}

/** The intent succeeded — a durable job exists. The next submit is a new intent. */
export function completeIntent(scope = 'scan') { dropStored(scope) }

/** The server PROVED nothing was created. Safe to start fresh; do not call this when unsure. */
export function abandonIntent(scope = 'scan') { dropStored(scope) }

/** Is an intent currently open? Exposed for tests and for a "reconciling…" affordance. */
export function hasOpenIntent(scope = 'scan') { return readStored(scope) !== null }

/**
 * Should a failed attempt keep its key so the next one can reconcile?
 *
 * True whenever the outcome is UNKNOWN. A 503 from the pool-exhaustion handler is the interesting
 * case: it currently carries a blanket "No changes were made", but that claim is only provable
 * when the pool failed on a request's FIRST database touch — the handler's own docstring says so.
 * Treating it as certain would be trusting a message the server cannot always justify, and the
 * cost of being wrong is a duplicate scan, so it is treated as uncertain.
 *
 * A 4xx is the opposite: the request was rejected before any work, and holding the key would make
 * the NEXT, corrected submission silently resolve to nothing.
 */
export function outcomeIsUncertain(status) {
  if (status === undefined || status === null) return true      // network error, timeout, abort
  if (status >= 400 && status < 500) return false               // rejected, nothing created
  return true                                                    // 5xx and anything unrecognised
}
