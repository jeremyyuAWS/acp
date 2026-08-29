// ADR 0042 — the durable lifecycle history of one RUN, normalized for rendering.
//
// THE BACKING DATA, and it is real. `GET /scans/{id}/history` → `store.list_scan_events`, rows the
// pipeline appends at each run-level transition (handlers.py, routes/scans.py, worker.py). Every
// event is `{event_id, scan_id, seq, occurred_at, kind, phase, job_id, worker_id, attempt, detail,
// owner_email}`. Nothing here is derived from a live stream or a poll: this is Postgres, so it
// survives the Redis TTL, a replica restart, and an ACA revision rollout — the whole point of the
// ADR, and the reason this panel can answer "what happened?" about a run that finished yesterday.
//
// WHAT THIS LOG CONTAINS, precisely, because the shape of a "history" panel implies more:
//   · RUN-LEVEL TRANSITIONS ONLY. Not per-file progress and not the live activity headline (which
//     writes up to 5×/second and is deliberately excluded — see the scan_events schema comment).
//     "Which document was being read at 14:03" is not answerable from here and never will be.
//   · Nothing about ASSESS. These are Discover-run events; assessment has its own surfaces.
//   · No durations. The gaps between timestamps are real and a reader can see them, but this
//     module does not compute "took 4m 12s" — an event pair is not a phase boundary in general
//     (a retry re-runs earlier kinds), and a plausible-looking number derived from the wrong two
//     rows is worse than no number.
//
// DUPLICATES ARE REAL AND ARE SHOWN. ADR 0042's log is append-only: a reclaimed job produces a
// second `scan.claimed` with a different worker_id/attempt, and a re-delivered job can produce a
// second `scan.discovered`. The ADR's rule is that readers take the FIRST terminal event by seq —
// so `outcome` below reads the first terminal row, while the list renders every row. Hiding the
// repeats would erase the evidence that a run was retried, which is most of what this panel is
// for.

/** Every kind the backend can append, and the sentence it stands for. Mirrors
 *  `Store.SCAN_EVENT_KINDS`; a kind absent here still renders, using its raw value. */
export const KIND_LABEL = {
  'scan.queued': 'Queued',
  'scan.claimed': 'Worker assigned',
  'scan.listing_started': 'Listing started',
  'scan.listing_complete': 'Listing complete',
  'scan.inventory_saved': 'Inventory saved',
  'scan.lifecycle_applied': 'Lifecycle rules applied',
  'scan.discovered': 'Discovery complete',
  'scan.assess_started': 'Assessment started',
  'scan.retrying': 'Retrying',
  'scan.paused': 'Paused',
  'scan.resumed': 'Resumed',
  'scan.cancelled': 'Cancelled',
  'scan.completed': 'Completed',
  'scan.failed': 'Failed',
  'scan.interrupted': 'Interrupted',
}

// Kinds that END a run, in the ADR's sense — the ones "take the first terminal event" refers to.
const TERMINAL = new Set(['scan.discovered', 'scan.completed', 'scan.failed', 'scan.cancelled',
                          'scan.interrupted'])

// Kinds that mean something went wrong, for the severity mark. `scan.retrying` is NOT an outcome —
// a run that retried and then succeeded is a success — but it is worth marking, because an
// operator scanning this list for "why was it slow" is looking for exactly these rows.
const BAD = new Set(['scan.failed', 'scan.interrupted'])
const WARN = new Set(['scan.retrying', 'scan.cancelled'])

/** The `detail` keys worth printing per kind, in order, with their labels. Explicit rather than
 *  "render every key" so a backend that starts recording a new internal field does not silently
 *  push it onto an operator's screen. */
const DETAIL_FIELDS = {
  'scan.queued': [['source', 'source'], ['job_type', 'job type']],
  'scan.claimed': [['source', 'source']],
  'scan.listing_started': [['source', 'source']],
  'scan.listing_complete': [['files_found', 'files'], ['folders_visited', 'folders'],
                            ['truncated', 'truncated']],
  'scan.inventory_saved': [['new', 'new'], ['updated', 'updated'], ['failed', 'failed']],
  'scan.lifecycle_applied': [['rules_enabled', 'rules'], ['matches', 'matches'],
                             ['archive', 'archive'], ['delete', 'delete']],
  'scan.discovered': [['files_found', 'files'], ['source', 'source']],
  'scan.completed': [['files', 'files']],
  'scan.retrying': [['error_class', 'error class'], ['last_error', 'error']],
  'scan.failed': [['reason', 'reason'], ['message', 'error']],
}

function summarize(kind, detail) {
  if (!detail || typeof detail !== 'object') return []
  const fields = DETAIL_FIELDS[kind]
  const pairs = []
  for (const [key, label] of fields || []) {
    const v = detail[key]
    // `false` and `0` are real values worth showing (truncated:false is the honest "we got it
    // all"); only genuinely absent ones are dropped.
    if (v === undefined || v === null || v === '') continue
    pairs.push({ label, value: typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v) })
  }
  return pairs
}

/**
 * One event, normalized.
 * @returns {{seq, kind, label, at, phase, jobId, workerId, attempt, severity, fields, isTerminal}}
 */
export function normalizeEvent(e) {
  const kind = String(e?.kind || '')
  return {
    seq: typeof e?.seq === 'number' ? e.seq : null,
    kind,
    label: KIND_LABEL[kind] || kind,
    at: e?.occurred_at || null,
    phase: e?.phase || null,
    jobId: e?.job_id || null,
    workerId: e?.worker_id || null,
    // Only shown when it means something: attempt 1 is the ordinary case and printing "attempt 1"
    // on every row of every healthy run would bury the attempt 3 that matters.
    attempt: typeof e?.attempt === 'number' && e.attempt > 1 ? e.attempt : null,
    severity: BAD.has(kind) ? 'bad' : WARN.has(kind) ? 'warn' : 'ok',
    fields: summarize(kind, e?.detail),
    isTerminal: TERMINAL.has(kind),
  }
}

/**
 * The whole panel's model.
 *
 * @param raw the endpoint's body, or null when the request failed (which the caller distinguishes
 *            from an empty history — see api.js's getScanHistory).
 * @returns {{available, events, outcome, retries, latestSeq, workers}}
 *   outcome    the FIRST terminal event, per ADR 0042's read rule — not the last row, which on a
 *              re-delivered job is a duplicate of it.
 *   retries    how many scan.retrying rows the run carries; 0 for a clean run.
 *   workers    distinct worker ids seen, so "two workers touched this run" is visible at a glance.
 */
export function normalizeHistory(raw) {
  if (!raw || typeof raw !== 'object' || raw.available === false) {
    return { available: false, events: [], outcome: null, retries: 0, latestSeq: null, workers: [] }
  }
  const events = (Array.isArray(raw.events) ? raw.events : []).map(normalizeEvent)
  const outcome = events.find((e) => e.isTerminal) || null
  const workers = [...new Set(events.map((e) => e.workerId).filter(Boolean))]
  return {
    available: true,
    events,
    outcome,
    retries: events.filter((e) => e.kind === 'scan.retrying').length,
    latestSeq: typeof raw.latest_seq === 'number' ? raw.latest_seq : null,
    workers,
  }
}
