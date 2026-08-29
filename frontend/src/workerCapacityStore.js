// Shared GET /control/workers/capacity poller. Discover.jsx and QueuePanel.jsx both want the
// same 30s-fresh Azure capacity data whenever the worker tier is externally managed, and until
// now each ran its own independent setInterval — doubling the Azure Monitor API calls the moment
// both are mounted at once (Discover left open in a background tab while Monitor is active, or
// the same account open in two browser tabs). This collapses that to exactly one poller,
// reference-counted so it only runs while at least one consumer actually wants the data, and
// hands a newly-subscribing consumer the last known value immediately rather than a null flash
// before its own first tick.
//
// Deliberately a plain module-level singleton, not a React context — the two consumers don't
// share a common ancestor component, so a context provider would mean wrapping something far
// above either of them just to thread this one value down.

import { useEffect, useState } from 'react'
import { getWorkerCapacity } from './api.js'

const POLL_MS = 30000

let cached = null
let listeners = new Set()
let timer = null
let inFlight = null   // the current poll()'s promise, so a fast subscribe/unsubscribe/subscribe
                       // (e.g. React StrictMode's double-invoke) can't fire two overlapping fetches

function poll() {
  if (inFlight) return inFlight
  inFlight = getWorkerCapacity()
    .then((d) => {
      cached = d
      listeners.forEach((fn) => fn(cached))
    })
    .catch(() => {})   // a failed poll leaves `cached` at its last good value, same as each
                        // consumer's own .catch(() => {}) did before this was shared
    .finally(() => { inFlight = null })
  return inFlight
}

function start() {
  if (timer) return
  poll()
  timer = setInterval(poll, POLL_MS)
}

function stop() {
  if (!timer) return
  clearInterval(timer)
  timer = null
  cached = null   // the next subscriber gets a fresh fetch, not a value that may be stale by the
                   // time anything is listening again — matches every existing consumer's own
                   // per-mount `useState(null)` starting point, so this is not a behavior change.
}

/** Subscribe to capacity updates. `fn` is called with the cached value immediately if one exists,
 *  then again on every successful poll. Returns an unsubscribe function. The underlying poller
 *  starts on the first subscriber and stops on the last — callers that gate their own
 *  subscription on `enabled` (see useWorkerCapacity below) get polling that only ever runs while
 *  someone is actually looking. */
export function subscribeWorkerCapacity(fn) {
  listeners.add(fn)
  if (listeners.size === 1) start()
  if (cached) fn(cached)
  return () => {
    listeners.delete(fn)
    if (listeners.size === 0) stop()
  }
}

/** React hook wrapping subscribeWorkerCapacity. `enabled` mirrors each caller's own
 *  externally-managed check (Discover.jsx's `runtime_mode === 'distributed' && alive`,
 *  QueuePanel.jsx's equivalent) — subscribes only while true, and resets to null when it flips
 *  false so a component that stops being externally managed doesn't keep showing stale Azure
 *  data it no longer has a live subscription backing. */
export function useWorkerCapacity(enabled) {
  const [capacity, setCapacity] = useState(null)
  useEffect(() => {
    if (!enabled) { setCapacity(null); return undefined }
    return subscribeWorkerCapacity(setCapacity)
  }, [enabled])
  return capacity
}

// Test-only escape hatch: the module-level singleton state above persists across test files in
// the same vitest worker otherwise, and there is no other way to reset it between tests.
export function _resetForTests() {
  if (timer) clearInterval(timer)
  timer = null
  cached = null
  listeners = new Set()
  inFlight = null
}
