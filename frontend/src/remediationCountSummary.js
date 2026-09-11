import { workflowStatusOf } from './remediationInboxModel.js'
import { exclusionReason } from './batchReviewSelection.js'

// How many FINDINGS a review item covers. A hitl_queue row is one (document, criterion) pair and
// carries the scanner's own count for it, so twelve review items can be thirteen findings — the
// difference between the number a run's logs report and the number of cards in the inbox. One is
// not the other, and neither is wrong; what was missing was any way to reconcile them on screen.
const findingsIn = (row) => {
  const count = row?._raw?.finding_count ?? row?.finding_count
  return Number.isFinite(count) && count > 0 ? count : 1
}

export function remediationReviewCounts(rows = [], decisions = {}, drafts = {}) {
  const pending = rows.filter(row => !row.autoApplied && ['needs-review', 'manual', 'blocked'].includes(workflowStatusOf(row, decisions)))
  const ready = pending.filter(row => !exclusionReason(row, decisions, drafts))
  const manual = pending.filter(row => workflowStatusOf(row, decisions) === 'manual')
  const individual = pending.filter(row => workflowStatusOf(row, decisions) === 'needs-review' && exclusionReason(row, decisions, drafts))
  return { pendingItems: pending.length, ready: ready.length, manual: manual.length, individual: individual.length,
    findings: pending.reduce((total, row) => total + findingsIn(row), 0),
    documents: new Set(pending.map(row => row.file).filter(Boolean)).size,
    inspection: rows.filter(row => row.autoApplied && workflowStatusOf(row, decisions) !== 'completed').length }
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
