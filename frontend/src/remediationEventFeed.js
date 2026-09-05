// User-facing projection of the durable remediation lifecycle log. The event is narration, not
// state: counters and terminality continue to come only from the reconciled run snapshot.
export const MAX_VISIBLE_REMEDIATION_EVENTS = 10

const n = (value, noun) => {
  const amount = Number(value)
  const plural = noun.endsWith('fix') ? `${noun}es` : `${noun}s`
  return Number.isFinite(amount) ? `${amount.toLocaleString()} ${amount === 1 ? noun : plural}` : noun
}

const file = (event) => event?.detail?.file || 'Document'

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
    default:
      return null
  }
}

export function eventTone(kind) {
  if (kind === 'remediate.verification_failed' || kind === 'remediate.delivery_failed') return 'error'
  if (kind === 'remediate.review_requested') return 'attention'
  if (kind === 'remediate.verified' || kind === 'remediate.delivered' || kind === 'remediate.document_completed') return 'success'
  return 'neutral'
}

export function addRemediationEvent(previous, event, id, limit = MAX_VISIBLE_REMEDIATION_EVENTS) {
  const line = remediationEventLine(event)
  if (!line) return previous
  const key = id == null ? `${event.kind}:${event.occurred_at || ''}:${line}` : String(id)
  if (previous.some((row) => row.key === key)) return previous
  return [{ key, id: id == null ? null : String(id), line, kind: event.kind,
            tone: eventTone(event.kind), occurredAt: event.occurred_at || null }, ...previous]
    .slice(0, limit)
}
