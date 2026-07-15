// Bounded auto-draft gate.
//
// The AI Work Inbox renders EVERY pending finding as its own EvidenceCard at once (Remediate maps
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

// Run `fn` (an async thunk) once a slot is free. Always releases the slot — even if `fn` throws —
// so one failed vision call never permanently shrinks the pool. Resolves/rejects with fn's result.
export async function runAutoDraft(fn) {
  await new Promise((resolve) => { waiters.push(resolve); pump() })
  try {
    return await fn()
  } finally {
    active -= 1
    pump()
  }
}

// Test seam — current in-flight count and queue depth.
export function _gateState() { return { active, queued: waiters.length } }
export const _MAX_CONCURRENT = MAX_CONCURRENT
