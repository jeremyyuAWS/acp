import { exclusionReason } from './batchReviewSelection.js'
import { isAiAssistedDraft, optionalInspectionOf, workflowStatusOf } from './remediationInboxModel.js'

// Only admitted server work changes a pending proposal's UI queue. Standing
// consent alone cannot prove source freshness or the writer's eligibility.
export function automaticReviewQueue(rows = [], policy = {}, decisions = {}) {
  policy ??= {}
  return rows.map(row => {
    const raw = row._raw || row
    const marker = raw.automatic_approval || row.automatic_approval || (raw.auto_approval_status ? {state:raw.auto_approval_status,run_id:raw.auto_approval_run_id,source_revision:raw.auto_approval_source_revision} : null)
    const unmarked = row.automaticQueued ? {...row,automaticQueued:false} : row
    const admitted = policy.enabled === true && policy.supported !== false && policy.run_id && policy.source_revision != null
      && marker?.run_id === policy.run_id && marker.source_revision === policy.source_revision
      && ['queued','processing','checking'].includes(marker.state)
    if (!admitted || optionalInspectionOf(row) || workflowStatusOf(unmarked,decisions) !== 'needs-review'
        || !isAiAssistedDraft(row) || exclusionReason(unmarked,decisions)) return unmarked
    return {...row,automaticQueued:true,automaticQueueLabel:marker.state === 'checking' ? 'Queued for automatic checks' : 'Queued for automatic application'}
  })
}
