// User-facing projection of the durable remediation lifecycle log. The event is narration, not
// state: counters and terminality continue to come only from the reconciled run snapshot.
export const MAX_VISIBLE_REMEDIATION_EVENTS = 10

const n = (value, noun) => {
  const amount = Number(value)
  const plural = noun.endsWith('fix') ? `${noun}es` : `${noun}s`
  return Number.isFinite(amount) ? `${amount.toLocaleString()} ${amount === 1 ? noun : plural}` : noun
}

// The document's NAME, in the order the server can supply it:
//
//   1. `document` — the structured column (ADR 0052). Every event written since carries it.
//   2. `detail.file` — where the name lived before the column existed. The log is DURABLE, so
//      rows written the old way are still replayed on resume; dropping this fallback would blank
//      the names in exactly the history a reconnecting client came back for.
//   3. a generic noun — used when the run's privacy policy suppressed the name (PRD §22), and
//      when neither field is present.
//
// It never invents a name, and it never treats a suppressed event as an unnamed one: suppression
// is a decision the server made and `documentLabel` says so, so the line reads "a document"
// rather than implying ACP does not know which.
const file = (event) => event?.document || event?.detail?.file
  || (event?.document_suppressed ? 'a document' : 'Document')

// Which document an event belongs to, for grouping several parallel documents' histories apart.
// `document_ref` is a per-run handle that survives suppression — the whole reason it exists — so
// grouping keeps working on a run whose names are withheld.
export const eventDocumentKey = (event) => event?.document_ref || event?.document
  || event?.detail?.file || null

export function remediationEventLine(event) {
  const detail = event?.detail || {}
  switch (event?.kind) {
    case 'remediate.accepted':
      return `Remediation accepted${Number.isFinite(Number(detail.documents)) ? ` for ${n(detail.documents, 'document')}` : ''}`
    case 'remediate.fix_applied':
      return `${n(detail.fixes, 'approved fix')} applied to ${file(event)}`
    case 'remediate.verified':
      return `${n(detail.fixes, 'fix')} independently verified for ${file(event)}`
    case 'remediate.verification_failed':
      return `${n(detail.fixes, 'fix')} did not pass re-scan for ${file(event)}`
    case 'remediate.delivered':
      return `Corrected copy of ${file(event)} saved to the source provider`
    case 'remediate.delivery_failed':
      return `Corrected copy of ${file(event)} retained in ACP; provider delivery failed`
    case 'remediate.review_requested':
      return `Manual review requested for ${file(event)}${detail.criterion ? ` · WCAG ${detail.criterion}` : ''}`
    case 'remediate.document_completed':
      return `${file(event)} remediation finished`
    // ── human actions on the run ──────────────────────────────────────────────
    // The ACTOR is deliberately absent from these lines, and from the events behind them: the
    // feed is replayed to every authorised viewer of the run, and naming who pressed the button
    // would put one user's identity on another's screen. The audit trail records it (PRD §13);
    // the narrative records that it happened.
    case 'remediate.delivery_retry_requested':
      return `Re-sending the corrected copy of ${file(event)}${detail.destination_provider ? ` to ${detail.destination_provider}` : ''} — no fix re-applied`
    case 'remediate.delivery_retry_refused':
      return `Delivery of ${file(event)} was not retried${detail.reason ? ` · ${detail.reason.replace(/_/g, ' ')}` : ''}`
    case 'remediate.cancel_requested':
      return 'Stopping the run · corrected copies already made are kept'
    case 'remediate.paused':
      return 'Run paused · work not yet started is held'
    case 'remediate.resumed':
      return 'Run resumed'
    default:
      return null
  }
}

export function eventTone(kind) {
  if (kind === 'remediate.verification_failed' || kind === 'remediate.delivery_failed') return 'error'
  if (kind === 'remediate.review_requested' || kind === 'remediate.delivery_retry_refused'
      || kind === 'remediate.cancel_requested' || kind === 'remediate.paused') return 'attention'
  if (kind === 'remediate.verified' || kind === 'remediate.delivered' || kind === 'remediate.document_completed') return 'success'
  return 'neutral'
}

export function addRemediationEvent(previous, event, id, limit = MAX_VISIBLE_REMEDIATION_EVENTS) {
  const line = remediationEventLine(event)
  if (!line) return previous
  const key = id == null ? `${event.kind}:${event.occurred_at || ''}:${line}` : String(id)
  if (previous.some((row) => row.key === key)) return previous
  return [{ key, id: id == null ? null : String(id), line, kind: event.kind,
            tone: eventTone(event.kind), occurredAt: event.occurred_at || null,
            documentKey: eventDocumentKey(event),
            // The SERVER classifies material vs lease/heartbeat activity; the browser must not
            // re-derive it from the kind string, or the two ends drift the moment a kind is
            // added. Absent (an older server, or a replayed row) reads as unknown — which is
            // neither true nor false, and is why this is `?? null` rather than `|| false`.
            material: event.material == null ? null : !!event.material,
            attempt: event.attempt == null ? null : Number(event.attempt),
            phase: event.phase || null,
            correlationId: event.correlation_id || null }, ...previous]
    .slice(0, limit)
}

// The per-document histories PRD §6D needs: several documents remediating at once, each with its
// own ordered account, from one interleaved feed.
//
// ORDER IS `id` (the event's seq), not arrival and not `occurredAt`. Arrival order is wrong after
// a resume — replayed history arrives after live frames a client already had — and `occurred_at`
// is a wall clock written by whichever replica ran the job, which ADR 0042 rejected as a cursor
// for exactly this reason. `seq` is the per-scan monotonic the stream resumes on, so ordering by
// it makes each document's history identical whether it was streamed live or replayed.
export function documentHistories(rows = []) {
  const byDocument = new Map()
  for (const row of rows) {
    if (!row?.documentKey) continue
    if (!byDocument.has(row.documentKey)) byDocument.set(row.documentKey, [])
    byDocument.get(row.documentKey).push(row)
  }
  for (const history of byDocument.values()) {
    history.sort((a, b) => {
      const left = Number(a.id), right = Number(b.id)
      if (Number.isFinite(left) && Number.isFinite(right)) return left - right
      return 0
    })
  }
  return byDocument
}
