import { STATE_LABELS, stageDefinition, validStageActions } from './stageDefinitions.js'
import { canonicalStageViewModels } from './stageAccountingModel.js'

const number = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null)
const PIPELINE_STAGE_ORDER = {
  discover: 0, assess: 1, remediate: 2, release: 3,
}

const VIEW_STAGE = {
  discover: 'discover', assess: 'assess', remediate: 'remediate',
  publish: 'release', monitor: 'conformance',
}

function workflowRevisionStages(lineage) {
  const workflowRevision = number(lineage?.workflow_revision)
  return (Array.isArray(lineage?.stages) ? lineage.stages : [])
    .filter((stage) => PIPELINE_STAGE_ORDER[stage.stage] != null
      && (workflowRevision == null || number(stage.workflow_revision) === workflowRevision))
}

/**
 * One authoritative snapshot per stage in the current workflow revision. A downstream stage
 * always owns the workflow once it exists: a delayed upstream event cannot make Discover current
 * again after Assess has started. Revisions only choose between executions of the SAME stage.
 */
export function canonicalWorkflowStages(lineage) {
  const newestByStage = new Map()
  workflowRevisionStages(lineage).forEach((stage) => {
    const previous = newestByStage.get(stage.stage)
    if (!previous || number(stage.revision) > number(previous.revision)
      || (number(stage.revision) === number(previous.revision)
        && String(stage.last_durable_update_at || '') > String(previous.last_durable_update_at || ''))) {
      newestByStage.set(stage.stage, stage)
    }
  })
  return [...newestByStage.values()].sort((left, right) =>
    PIPELINE_STAGE_ORDER[left.stage] - PIPELINE_STAGE_ORDER[right.stage])
}

export function priorCanonicalStages(lineage, view) {
  const currentStage = VIEW_STAGE[view]
  const currentOrder = currentStage === 'conformance' ? 4 : PIPELINE_STAGE_ORDER[currentStage]
  if (currentOrder == null) return []
  const workflowRevision = number(lineage?.workflow_revision)
  const stages = Array.isArray(lineage?.stages) ? lineage.stages : []
  const matching = stages.filter((stage) => {
    const order = PIPELINE_STAGE_ORDER[stage.stage]
    return order != null && order < currentOrder
      && workflowRevision != null
      && number(stage.workflow_revision) === workflowRevision
  })
  const newestByStage = new Map()
  matching.forEach((stage) => {
    const previous = newestByStage.get(stage.stage)
    if (!previous || Number(stage.revision || 0) > Number(previous.revision || 0)) {
      newestByStage.set(stage.stage, stage)
    }
  })
  return [...newestByStage.values()].sort((left, right) =>
    PIPELINE_STAGE_ORDER[left.stage] - PIPELINE_STAGE_ORDER[right.stage])
}

export function stageNeedsAttention(snapshot) {
  return snapshot?.integrity?.ok === false
    || snapshot?.reconciliation?.exact === false
    || ['failed', 'cancelled', 'integrity_failed', 'reconciling'].includes(snapshot?.state)
}

export function canonicalStageCardModel(snapshot, context = {}) {
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
  const definition = stageDefinition(snapshot.stage)
  const views = canonicalStageViewModels(snapshot, context)
  const stateLabel = stopping ? 'Stopping safely' : (STATE_LABELS[snapshot.state] || 'Status unavailable')
  return {
    stage: snapshot.stage,
    stageLabel: definition?.label || 'Stage',
    stageColor: definition?.color || null,
    stateLabel,
    state: snapshot.state,
    actions: validStageActions(snapshot.state, {
      cancelRequested: stopping, isCurrent: context.isCurrent !== false,
    }),
    compact: views.compact,
    expanded: views.expanded,
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
      buckets: views.expanded.counters.map(({ key, label }) => [label, number(domain.buckets[key])]),
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
  const stages = canonicalWorkflowStages(lineage)
  if (!stages.length) return null
  return [...stages].sort((left, right) => {
    const stageOrder = (PIPELINE_STAGE_ORDER[right.stage] ?? -1)
      - (PIPELINE_STAGE_ORDER[left.stage] ?? -1)
    if (stageOrder) return stageOrder
    const updated = String(right.last_durable_update_at || '')
      .localeCompare(String(left.last_durable_update_at || ''))
    return updated || Number(right.revision || 0) - Number(left.revision || 0)
  })[0]
}
