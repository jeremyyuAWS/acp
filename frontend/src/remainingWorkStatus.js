import { workflowCounts } from './remediationInboxModel.js'

// Recent event evidence is narration, never a substitute for the reconciled counters.
const VISION = new Set(['remediate.vision_retry_pending', 'remediate.vision_retry_blocked', 'remediate.vision_retry_recovered', 'remediate.delivered'])
export function remainingWorkStatus({ events = [], rows = [], decisions = {}, snapshot = null } = {}) {
  const latest = new Map()
  const ordered = [...events].sort((a, b) => Number(b.id) - Number(a.id))
  for (const event of ordered) {
    if (!event.documentKey || !VISION.has(event.kind) || latest.has(event.documentKey)) continue
    latest.set(event.documentKey, event)
  }
  const notices = []
  const spendingFiles = new Set()
  const now = Date.parse(snapshot?.generated_at || '')
  for (const event of latest.values()) {
    if (event.kind === 'remediate.vision_retry_pending') notices.push({ key: event.key, label: 'AI retry queued', responsibility: 'ACP will retry automatically. No individual approval is needed for this retry.', tone: 'automatic' })
    if (event.kind === 'remediate.vision_retry_blocked') {
      if (event.reasonCode === 'vision_spending_reconciliation_required') {
        const recorded = Date.parse(event.occurredAt || '')
        const withinChecks = Number.isFinite(now) && Number.isFinite(recorded) && now >= recorded && now - recorded < 40 * 60 * 1000
        if (withinChecks && event.documentName) spendingFiles.add(event.documentName)
        notices.push({ key: event.key, label: withinChecks ? 'AI usage confirmation pending' : 'AI usage confirmation needs attention', responsibility: 'ACP checks previous usage only while a reconciliation retry is scheduled (up to eight checks). Another paid request waits for confirmation; unresolved spending may need attention.', tone: 'waiting' })
      }
      else if (event.reasonCode === 'vision_permission_or_budget_blocked') notices.push({ key: event.key, label: 'AI permission or spending limit needs attention', responsibility: 'Check the saved AI permission and available spending limit. ACP cannot send another request yet.', tone: 'review' })
      else notices.push({ key: event.key, label: 'Your review needed', responsibility: 'Automatic image-description attempts have stopped. Review the suggestion or provide an authored description.', tone: 'review' })
    }
  }
  // Only the missing caption draft belongs to this spending pause. Other
  // criteria, manual assignments and already authored proposals remain actionable.
  const counts = workflowCounts(rows.filter(row => {
    const criterion = String(row.rule_id || row.ruleId || row.sc || '').replace(/^(WCAG_?|SC_)/, '').replace(/_/g, '.')
    const missingCaption = criterion === '1.1.1' && row.status === 'pending'
      && row.hasProposal !== true && !row.after && !(row.proposals || []).some(p => p.proposed_value || p.proposed)
      && !row.rejectedFix && !decisions[row.id] && !decisions[row.file]
    return !(spendingFiles.has(row.file) && missingCaption)
  }), decisions)
  const review = counts['needs-review'] + counts.blocked
  if (review) notices.push({ key: 'review', label: 'Your review needed', responsibility: `${review.toLocaleString()} review item${review === 1 ? '' : 's'} need a decision, valid proposal, or recovery check. Auto-apply does not bypass these requirements.`, tone: 'review' })
  if (counts.manual) notices.push({ key: 'manual', label: 'Manual document edit needed', responsibility: `${counts.manual.toLocaleString()} review item${counts.manual === 1 ? '' : 's'} need a person to edit or resolve the document. These do not drain through AI automatically.`, tone: 'manual' })
  const age = snapshot?.progress?.material_age_s
  const checkpoint = typeof age === 'number' && Number.isFinite(age) && age >= 0 ? `Last saved progress ${Math.floor(age / 60)}m ${Math.floor(age % 60)}s ago.` : null
  const stalled = snapshot?.state === 'stalled'
  const recovery = stalled ? 'ACP has detected a stall. Check Live Operations for the worker or retry blocker; automatic recovery is not yet confirmed.'
    : snapshot?.retry_at ? 'A retry is scheduled. ACP will resume eligible work automatically.'
      : snapshot?.progress?.lease_healthy === true && !snapshot?.terminal ? 'A worker is still active. ACP continues monitoring its checkpoints.' : null
  return { notices, checkpoint, recovery, stalled }
}
