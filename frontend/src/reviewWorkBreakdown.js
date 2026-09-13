import { normSc, workflowStatusOf } from './remediationInboxModel.js'
import { exclusionReason } from './batchReviewSelection.js'

const FAILED = new Set(['failed', 'apply_failed', 'verification_failed'])
const AI_BLOCKED = new Set(['vision_permission_or_budget_blocked', 'vision_spending_reconciliation_required', 'ai_disabled_or_budget_zero', 'vision_pricing_not_verified'])

// One recorded review item gets one category. A suggestion, consent, or a missing
// draft is never evidence that an automatic operation is running.
export function reviewWorkCategory(row, decisions = {}, blockedCaptionFiles = new Set()) {
  const state = workflowStatusOf(row, decisions)
  if (state === 'completed') return 'results'
  if (state === 'awaiting-validation') return 'processing'
  const raw = row._raw || row
  const marker = row.automaticDisposition
  const reason = marker?.reason_code || marker?.reason || raw.reason_code || raw.failure_reason_code
  if (FAILED.has(String(row.status || '').toLowerCase()) || ['verification_failed', 'rescan_failed', 'application_failed'].includes(reason)) return 'failed-checks'
  const rule = normSc(row.rule_id || row.ruleId || row.sc)
  const hasValue = !!row.after || (row.proposals || raw.proposals || []).some(p => String(p.proposed_value || p.proposed || '').trim())
  const decision = decisions[row.id] || decisions[row.file]
  if (AI_BLOCKED.has(reason) || (rule === '1.1.1' && !hasValue && blockedCaptionFiles.has(row.file))) return 'blocked-ai'
  if (row.manual === true || row.rejectedFix || ['assigned', 'deferred'].includes(decision?.state)) return 'manual'
  if (row.aiDraftable === true && !hasValue || exclusionReason(row, decisions) === 'Missing proposal') return 'missing-proposals'
  if (marker?.responsibility === 'human' && hasValue) return 'review'
  if (state === 'manual') return 'manual'
  if (state === 'blocked') return 'status-checks'
  return 'review'
}

export function reviewWorkBreakdown(rows = [], decisions = {}, blockedCaptionFiles) {
  const counts = { results: 0, processing: 0, 'failed-checks': 0, 'blocked-ai': 0, manual: 0, 'missing-proposals': 0, 'status-checks': 0, review: 0 }
  for (const row of rows) counts[reviewWorkCategory(row, decisions, blockedCaptionFiles)] += 1
  return counts
}
