const STAGE_LABELS = {
  discover: 'Discover', assess: 'Assess', remediate: 'Remediate',
  release: 'Release', conformance: 'Conformance',
}

const STATE_LABELS = {
  queued: 'Waiting', processing: 'Processing', paused: 'Paused',
  processing_complete: 'Reconciling', reconciling: 'Reconciling',
  succeeded: 'Complete', failed: 'Failed', cancelled: 'Stopped manually',
  integrity_failed: 'Needs attention', superseded: 'Superseded',
}

const number = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null)
const PIPELINE_STAGE_ORDER = {
  discover: 0, assess: 1, remediate: 2, release: 3,
}

const DOMAIN_BUCKET_LABELS = {
  waiting: 'Waiting', processing: 'Processing', assessed: 'Assessed',
  published: 'Published · verified', completed_unverified: 'Completed · not verified',
  resolved_verified: 'Resolved · verified', awaiting_review: 'Awaiting review',
  approved_pending_verification: 'Approved · awaiting verification',
  unchanged_no_fix: 'Unchanged · no fix', failed: 'Failed', excluded: 'Excluded',
  superseded: 'Superseded', cancelled: 'Stopped manually', skipped: 'Skipped',
}

const domainBucketLabel = (key) => DOMAIN_BUCKET_LABELS[key]
  || String(key).replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())

export function canonicalStageCardModel(snapshot) {
  if (!snapshot) return null
  const work = snapshot.counts?.work_items || {}
  const reconciliation = snapshot.reconciliation || {}
  const domain = snapshot.domain_reconciliation || {}
  const domainAvailable = domain.available !== false
    && domain.buckets && typeof domain.buckets === 'object'
  const domainTotal = domainAvailable ? number(domain.total) : null
  const domainAccounted = domainAvailable
    ? (number(domain.accounted) ?? number(domain.partitioned)) : null
  const total = number(reconciliation.total) ?? number(work.total)
  const accounted = number(reconciliation.accounted)
  const integrityOk = snapshot.integrity?.ok !== false && reconciliation.exact !== false
    && (!domainAvailable || domain.exact !== false)
  const stopping = snapshot.control?.cancel_requested === true
    && !['cancelled', 'failed', 'succeeded'].includes(snapshot.state)
  const stateLabel = stopping ? 'Stopping safely' : (STATE_LABELS[snapshot.state] || 'Status unavailable')
  return {
    stage: snapshot.stage,
    stageLabel: STAGE_LABELS[snapshot.stage] || 'Stage',
    stateLabel,
    integrityOk,
    total,
    accounted,
    unit: reconciliation.unit || work.unit || 'work items',
    revision: number(snapshot.revision),
    workflowRevision: number(snapshot.workflow_revision),
    lastUpdatedAt: snapshot.last_durable_update_at || null,
    executionId: snapshot.execution_id || null,
    manifestId: snapshot.sealed_output?.manifest_id || snapshot.output_manifest_id || null,
    unaccounted: number(reconciliation.unaccounted),
    exact: reconciliation.exact === true,
    stopping,
    domain: domainAvailable ? {
      scope: domain.scope || null,
      equation: domain.equation || null,
      unit: domain.unit || 'items',
      total: domainTotal,
      accounted: domainAccounted,
      unaccounted: number(domain.unaccounted),
      exact: domain.exact === true,
      buckets: Object.entries(domain.buckets).map(([key, value]) => [
        domainBucketLabel(key), number(value),
      ]),
    } : null,
    workItems: [
      ['Completed', number(work.completed)],
      ['Failed', number(work.failed)],
      ['Skipped', number(work.skipped)],
      ['Processing', number(work.processing)],
      ['Waiting', number(work.queued)],
      ['Stopped manually', number(work.cancelled)],
    ],
  }
}

export function currentCanonicalStage(lineage) {
  const stages = Array.isArray(lineage?.stages) ? lineage.stages : []
  if (!stages.length) return null
  const live = stages.filter((stage) => !['succeeded', 'cancelled', 'failed', 'superseded']
    .includes(stage.state))
  const candidates = live.length ? live : stages
  return [...candidates].sort((left, right) => {
    if (!live.length) {
      const stageOrder = (PIPELINE_STAGE_ORDER[right.stage] ?? -1)
        - (PIPELINE_STAGE_ORDER[left.stage] ?? -1)
      if (stageOrder) return stageOrder
    }
    const updated = String(right.last_durable_update_at || '')
      .localeCompare(String(left.last_durable_update_at || ''))
    return updated || Number(right.revision || 0) - Number(left.revision || 0)
  })[0]
}
