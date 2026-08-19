// Bounded auto-draft gate.
//
// The Review queue renders EVERY pending finding as its own EvidenceCard at once (Remediate maps
// the whole queue). Now that an undrafted card generates its AI preview automatically instead of
// waiting for a "Draft with AI" click, firing on sight would launch a vision call for every
// undrafted card and image the moment the inbox opens — a thundering herd that stalls a single
// local/GPU Ollama and can time out the whole batch.
//
// This gate caps how many auto-drafts run concurrently across ALL cards; the rest queue and start
// as slots free. Only the AUTOMATIC, en-masse path routes through it — a reviewer's own manual
// retry/refine click bypasses the gate, because one deliberate action is never a stampede.
const MAX_CONCURRENT = 2
let active = 0
const waiters = []

function pump() {
  while (active < MAX_CONCURRENT && waiters.length) {
    active += 1
    waiters.shift()()   // resolve the next waiter's slot promise
  }
}

// Circuit breaker for a MISSING MODEL, which is a property of the deployment and not of the card.
//
// A reachable Ollama that never pulled the model 503s every draft identically, so a 40-finding
// inbox used to discover the same missing model 40 times — 40 requests, and the reviewer told
// nothing until each card's own attempt came back. Once one auto-draft reports it (api.js sets
// `aiModelNotPulled` off the server's marker), the rest short-circuit: they reject IMMEDIATELY
// with that same error, so every card still shows the reason — naming the model and the
// `ollama pull` — without asking again.
//
// Deliberately NOT tripped by an ordinary draft failure. A model that IS pulled and merely failed
// (timeout, a wedged replica, an empty completion) stays retryable per card, because the next card
// genuinely might succeed. Only a capability failure is global.
let modelMissing = null   // the Error to replay, or null while the breaker is closed

// Run `fn` (an async thunk) once a slot is free. Always releases the slot — even if `fn` throws —
// so one failed vision call never permanently shrinks the pool. Resolves/rejects with fn's result.
export async function runAutoDraft(fn) {
  // Short-circuit before taking a slot: a doomed call must not occupy the pool or the network.
  if (modelMissing) throw modelMissing
  await new Promise((resolve) => { waiters.push(resolve); pump() })
  try {
    // Re-check after the wait. A 40-card inbox queues most of its drafts behind the first two,
    // and those are exactly the ones that discover the missing model — a waiter that only
    // checked on entry would still fire every queued request.
    if (modelMissing) throw modelMissing
    return await fn()
  } catch (e) {
    if (e?.aiModelNotPulled) modelMissing = e
    throw e
  } finally {
    active -= 1
    pump()
  }
}

// Re-arm. A reviewer's manual retry is a deliberate act that usually follows `ollama pull`, so it
// must be able to prove the model is back — the automatic path alone would never try again.
export function resetAutoDraftBreaker() { modelMissing = null }

// Test seam — current in-flight count and queue depth. Deliberately still just those two: the
// existing concurrency tests assert its exact shape, and the breaker is a separate concern.
export function _gateState() { return { active, queued: waiters.length } }
// Test seam — whether the missing-model breaker is open.
export function _breakerTripped() { return !!modelMissing }
export const _MAX_CONCURRENT = MAX_CONCURRENT
