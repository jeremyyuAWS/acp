import { workflowStatusOf, matchesWorkflow } from './remediationInboxModel.js'
const AUTO_RULES = new Set(['1.1.1','2.4.4','2.4.9','4.1.2','1.3.3','3.1.2','2.4.6'])
export function automaticReviewResponsibility(row, decisions = {}) {
  const status=workflowStatusOf(row, decisions)
  if (status==='completed') return 'results'
  if (row.automaticQueued || (status === 'awaiting-validation' && ['queued','checking','applying','verifying','processing'].includes(row.automaticDisposition?.state))) return 'acp'
  const decision=decisions[row.id] || decisions[row.file]
  if (['assigned','deferred','rejected'].includes(decision?.state) || row.rejectedFix || row.manual === true) return 'human'
  const rule=String(row.rule_id || row.ruleId || '').replace(/^(WCAG_?|SC_)/,'').replace(/_/g,'.')
  if (row.automaticDisposition?.responsibility==='human' || (rule && !AUTO_RULES.has(rule))) return 'human'
  // No admitted job is unknown, not automatic processing or a verified fix.
  return 'check'
}
export function matchesAutomaticReview(row, tab, decisions={}, enabled=false) {
  if (!enabled) return matchesWorkflow(row,tab,decisions)
  if (tab==='review') return automaticReviewResponsibility(row,decisions)==='human'
  if (tab==='status-check') return automaticReviewResponsibility(row,decisions)==='check'
  if (tab==='awaiting-validation') return automaticReviewResponsibility(row,decisions)==='acp'
  return matchesWorkflow(row,tab,decisions)
}
