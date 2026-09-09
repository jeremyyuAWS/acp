import { workflowStatusOf } from './remediationInboxModel.js'
import { exclusionReason } from './batchReviewSelection.js'

export function remediationReviewCounts(rows = [], decisions = {}, drafts = {}) {
  const pending = rows.filter(row => !row.autoApplied && ['needs-review', 'manual', 'blocked'].includes(workflowStatusOf(row, decisions)))
  const ready = pending.filter(row => !exclusionReason(row, decisions, drafts))
  const manual = pending.filter(row => workflowStatusOf(row, decisions) === 'manual')
  const individual = pending.filter(row => workflowStatusOf(row, decisions) === 'needs-review' && exclusionReason(row, decisions, drafts))
  return { pendingItems: pending.length, ready: ready.length, manual: manual.length, individual: individual.length,
    documents: new Set(pending.map(row => row.file).filter(Boolean)).size,
    inspection: rows.filter(row => row.autoApplied && workflowStatusOf(row, decisions) === 'needs-review').length }
}
export function reviewBadgeTitle(count) {
  return `${count} review item${count === 1 ? '' : 's'} requiring attention`
}
export function remediationDiffPage(value) {
  if (Array.isArray(value)) return { items: value, total: null, documents: null, complete: false }
  const items = Array.isArray(value?.items) ? value.items : []
  const valid = Number.isInteger(value?.total) && value.total >= items.length && Number.isInteger(value?.documents)
    && value.documents >= 0 && value.documents <= value.total && value.loaded === items.length
  return { items, total: valid ? value.total : null, documents: valid ? value.documents : null,
    complete: valid && value.complete === true && items.length === value.total }
}
