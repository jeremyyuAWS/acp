// The client's half of the remediation run contract (PRD §8/§9). It NORMALIZES and it JUDGES
// FRESHNESS. It does not decide what state the run is in, and it does not compute a counter from
// other counters — both of those live on the server, in api/remediation_run.py, because every
// attempt to assemble them in the browser produced a screen whose parts contradicted each other.
//
// The one rule that governs every function here: UNKNOWN IS NOT ZERO. A field the snapshot does
// not carry comes back as null and renders as "—". Substituting 0 is how a telemetry gap came to
// read as a healthy, empty queue.

// The document partition, in the order the panel reads them. Each carries its DEFINITION, which
// is shown to the user — "Completed" and "Verified" both meant three different things on the old
// screen, and a glossary that lives only in a PRD is a glossary nobody reads.
export const COUNTERS = [
  { key: 'completed', label: 'Completed',
    definition: 'Document reached a terminal successful outcome for this run' },
  { key: 'processing', label: 'Processing',
    definition: 'A valid worker attempt is actively changing or verifying the document' },
  { key: 'waiting', label: 'Waiting',
    definition: 'Eligible work has not yet been claimed' },
  { key: 'review', label: 'Review',
    definition: 'Automatic work stopped because a human decision or authored value is required' },
  { key: 'failed', label: 'Failed',
    definition: 'No automatic attempts remain' },
  { key: 'skipped', label: 'Skipped',
    definition: 'In scope, but no eligible approved fix was applied' },
]

// Secondary metrics. Every label names its UNIT (PRD §6C): "Verified" alone was read as documents
// on one line and as fixes on the next, on the same screen, from the same number.
export const SECONDARY = [
  { key: 'fixesApplied', label: 'Fixes applied', path: ['fixes', 'applied'] },
  { key: 'fixesVerified', label: 'Fixes verified', path: ['fixes', 'verified'] },
  { key: 'verificationFailures', label: 'Verification failures', path: ['fixes', 'verification_failures'] },
  { key: 'documentsVerified', label: 'Documents verified', path: ['fixes', 'documents_verified'] },
  { key: 'delivered', label: 'Corrected copies delivered', path: ['delivery', 'delivered'] },
  { key: 'pendingDelivery', label: 'Corrected copies pending delivery', path: ['delivery', 'pending'] },
  { key: 'reviewItems', label: 'Review items', path: ['review', 'items'] },
]

const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null)
const at = (obj, path) => path.reduce((node, key) => (node == null ? undefined : node[key]), obj)

/** The six partition counters as rows, or null when the snapshot carries none. Never invents a 0. */
export function counterRows(snapshot) {
  const documents = snapshot?.documents
  if (!documents) return null
  return COUNTERS.map((c) => ({ ...c, value: num(documents[c.key]) }))
}

/** The secondary metrics that the snapshot actually carries. A metric it does not carry is omitted
 *  rather than shown at zero — the same rule RemediationRunHeader already applies to its counts. */
export function secondaryRows(snapshot) {
  if (!snapshot) return []
  return SECONDARY.map((s) => ({ ...s, value: num(at(snapshot, s.path)) }))
                  .filter((s) => s.value !== null)
}

/** Does the partition still sum to the scope, per THIS snapshot's own numbers?
 *  Returns null when either side is unknown — "cannot check" is not "checks out". */
export function partitionSums(snapshot) {
  const rows = counterRows(snapshot)
  const total = num(snapshot?.total_documents)
  if (!rows || total === null || rows.some((r) => r.value === null)) return null
  return rows.reduce((sum, r) => sum + r.value, 0) === total
}

/**
 * How much this panel's numbers can currently be trusted (PRD §9).
 *
 * `connected` is the transport's own answer, not an inference from data age: a stream that
 * dropped while the run happened to be idle produces fresh-looking numbers and no updates, and
 * that is precisely the case a green "Live" badge must not survive.
 *
 * @param snapshot   the last snapshot received, or null.
 * @param connected  true while the SSE stream is open; false while reconnecting or polling.
 * @param receivedAt epoch ms when that snapshot arrived in the browser.
 * @param now        epoch ms.
 */
export function freshness({ snapshot, connected = false, receivedAt = null, now = Date.now() } = {}) {
  if (!snapshot) {
    return { level: 'unknown', label: 'Unknown', ageS: null,
             detail: 'No confirmed update yet.' }
  }
  const ageS = receivedAt === null ? null : Math.max(0, Math.round((now - receivedAt) / 1000))
  const thresholds = snapshot.thresholds || {}
  const delayedAfter = num(thresholds.delayed_after_s) ?? 60
  const ageDetail = ageS === null ? 'Update age unknown.' : `Last confirmed update ${ageS}s ago.`

  // The server's own positive determination outranks anything measured here: it can see the
  // leases and the queue, and the browser can only see how long ago a frame arrived.
  if (snapshot.state === 'stalled') {
    return { level: 'stalled', label: 'Stalled', ageS,
             detail: `Progress has stopped. ${ageDetail}` }
  }
  if (snapshot.integrity && snapshot.integrity.ok === false) {
    return { level: 'unknown', label: 'Unknown', ageS,
             detail: `Some values could not be reconciled. ${ageDetail}` }
  }
  if (!connected) {
    return { level: 'reconnecting', label: 'Reconnecting', ageS,
             detail: `Live updates interrupted. ${ageDetail}` }
  }
  if (ageS !== null && ageS > delayedAfter) {
    return { level: 'delayed', label: 'Delayed', ageS,
             detail: `Updates are behind. ${ageDetail}` }
  }
  return { level: 'live', label: 'Live', ageS, detail: ageDetail }
}

/**
 * Should this later snapshot be applied on top of the one already rendered?
 *
 * A revision that has not advanced is the same run state re-sent; a revision that has GONE
 * BACKWARDS is a frame from a superseded read, and rendering it would walk the panel backwards.
 * PRD §17.6's "fetch a fresh snapshot before rendering later events" is the caller's job — this
 * is the predicate it asks.
 */
export function isNewer(previous, next) {
  if (!next) return false
  if (!previous) return true
  const a = num(previous.revision), b = num(next.revision)
  if (a === null || b === null) return true   // cannot compare: take the newer arrival
  return b >= a
}

/** The headline sentence: the server's message, plus what else the run is doing so a more severe
 *  state never hides live progress (PRD §7 — precedence decides the headline, not the whole
 *  story). Returns null when there is nothing to say. */
export function headline(snapshot) {
  if (!snapshot?.message) return null
  const also = snapshot.also || []
  const documents = snapshot.documents || {}
  const parts = []
  if (also.includes('running') && num(documents.processing)) {
    parts.push(`${documents.processing} still processing`)
  }
  if (snapshot.state !== 'waiting' && also.includes('waiting') && num(documents.waiting)) {
    parts.push(`${documents.waiting} waiting`)
  }
  return parts.length ? `${snapshot.message} · ${parts.join(' · ')}` : snapshot.message
}
