import { exclusionReason } from './batchReviewSelection.js'
import { isAiAssistedDraft, optionalInspectionOf, workflowStatusOf } from './remediationInboxModel.js'

// Only admitted server work changes a pending proposal's UI queue. Standing
// consent alone cannot prove source freshness or the writer's eligibility.
export function automaticReviewQueue(rows = [], policy = {}, decisions = {}) {
  policy ??= {}
  return rows.map(row => {
    const raw = row._raw || row
    const marker = raw.automatic_approval || row.automatic_approval || (raw.auto_approval_status ? {state:raw.auto_approval_status,run_id:raw.auto_approval_run_id,source_revision:raw.auto_approval_source_revision} : null)
    const exactSnapshots = !marker?.proposal_snapshot_ids || JSON.stringify(marker.proposal_snapshot_ids) === JSON.stringify(raw.proposal_snapshot_ids || row.proposal_snapshot_ids || [])
    const disposition = exactSnapshots && marker?.run_id === policy.run_id && marker?.source_revision === policy.source_revision ? marker : null
    const unmarked = {...row, automaticQueued:false, automaticDisposition:disposition, automaticReason:disposition?.reason || (policy.enabled === true ? 'This suggestion needs individual review or has not been admitted to automatic application.' : null)}
    const admitted = policy.enabled === true && policy.supported !== false && policy.run_id && policy.source_revision != null
      && exactSnapshots && marker?.run_id === policy.run_id && marker.source_revision === policy.source_revision
      && ['queued','processing','checking','applying','verifying'].includes(marker.state)
    if (!row.automaticQueued) delete unmarked.automaticQueued
    if (!admitted || optionalInspectionOf(row) || workflowStatusOf(unmarked,decisions) !== 'needs-review'
        || !isAiAssistedDraft(row) || exclusionReason(unmarked,decisions)) return unmarked
    return {...row,automaticQueued:true,automaticQueueLabel:({checking:'Checking automatic eligibility',queued:'Queued automatically',processing:'Applying…',applying:'Applying…',verifying:'Verifying…'})[marker.state]}
  })
}
