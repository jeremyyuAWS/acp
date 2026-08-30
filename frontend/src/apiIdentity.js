// Who is signed in, and which API they are signed in to — the scope key for anything cached
// per-user in the client.
//
// A separate module from api.js on purpose, for two reasons.
//
// It is a different concern. api.js is the fetch layer; this is session scope. A cache does not
// need to know how requests are made, only whose data it is holding.
//
// And it must stay reachable when api.js is mocked. Component tests mock './api.js' with a
// factory listing only the functions that component calls, so anything importing a NEW name from
// api.js breaks ~20 unrelated suites the moment it is added. The alternative — giving the cache
// defensive fallbacks for a missing identity — would mean the isolation guarantee silently
// degrades to "unscoped" exactly when something is misconfigured, which is the wrong failure
// direction for a guarantee about not showing one account another's data.
//
// The epoch is a counter, never the bearer token. A credential does not belong in a cache key,
// nor in the logs and error messages that cache keys end up in.

const BASE = import.meta.env.VITE_API ?? 'http://localhost:8077'

let _authEpoch = 0

/** The API this client talks to. Part of the scope key: a different backend is different data. */
export const apiBase = () => BASE

/**
 * A stamp for "who is signed in". Changes on sign-in, sign-out and account switch; never
 * decreases. Cache keys built on it stop matching the moment identity changes, so a response
 * fetched for one account can never be served to the next.
 */
export const authEpoch = () => _authEpoch

/**
 * Record an identity change. Called by api.js's token setters. Bumps ONLY on a real change —
 * those setters run on every render in places, and an epoch that moved each time would
 * invalidate every cache continuously.
 */
export const noteAuthChange = (was, now) => { if (was !== now) _authEpoch += 1 }

/** Test seam. */
export const _resetAuthEpoch = () => { _authEpoch = 0 }
