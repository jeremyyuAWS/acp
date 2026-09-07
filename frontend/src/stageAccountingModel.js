import { METRIC_UNITS, stageDefinition } from './stageDefinitions.js'

const number = (value) => typeof value === 'number' && Number.isFinite(value) ? value : null
const PENDING_STATES = new Set(['accepted', 'queued', 'processing', 'processing_complete', 'reconciling'])

export const VALUE_STATES = Object.freeze({
  known: 'known', unknown: 'unknown', pending: 'pending', stale: 'stale', inconsistent: 'inconsistent',
})

export function metricValue(value, {
  executionState = null, inconsistent = false, sourceRevision = null, currentRevision = null,
} = {}) {
  const numeric = number(value)
  const stale = numeric != null && number(sourceRevision) != null && number(currentRevision) != null
    && sourceRevision !== currentRevision
  let state = VALUE_STATES.known
  if (inconsistent) state = VALUE_STATES.inconsistent
  else if (stale) state = VALUE_STATES.stale
  else if (numeric == null) state = PENDING_STATES.has(executionState)
    ? VALUE_STATES.pending : VALUE_STATES.unknown
  return {
    value: numeric,
    state,
    display: state === VALUE_STATES.inconsistent ? 'Accounting temporarily inconsistent'
      : state === VALUE_STATES.pending ? 'Calculating…'
        : state === VALUE_STATES.unknown ? 'Not yet available'
          : state === VALUE_STATES.stale ? `${numeric.toLocaleString()} · from revision ${sourceRevision}`
            : numeric.toLocaleString(),
    sourceRevision: number(sourceRevision),
  }
}

function snapshotIsInconsistent(snapshot, domain) {
  return snapshot?.integrity?.ok === false || snapshot?.reconciliation?.exact === false
    || snapshot?.reconciliation_status === 'inconsistent' || domain?.exact === false
}

const unitFromSnapshot = (unit) => {
  if (unit === 'assessed findings') return METRIC_UNITS.findings
  if (unit === 'work items') return METRIC_UNITS.workItems
  return METRIC_UNITS.documents
}

/** Build the one primary metric shared by compact and expanded stage views. */
export function canonicalPrimaryMetric(snapshot, context = {}) {
  if (!snapshot) return null
  const definition = stageDefinition(snapshot.stage)
  const domain = snapshot.domain_reconciliation
  const available = domain?.available !== false && domain?.buckets
    && typeof domain.buckets === 'object'
  const reconciliation = available ? domain : (snapshot.reconciliation || {})
  const work = snapshot.counts?.work_items || {}
  const total = number(reconciliation.total) ?? (!available ? number(work.total) : null)
  const accounted = number(reconciliation.accounted) ?? number(reconciliation.partitioned)
  const inconsistent = snapshotIsInconsistent(snapshot, available ? domain : null)
  const valueOptions = {
    executionState: snapshot.state, inconsistent,
    sourceRevision: snapshot.workflow_revision,
    currentRevision: context.workflowRevision ?? snapshot.workflow_revision,
  }
  return {
    unit: available ? unitFromSnapshot(domain.unit) : METRIC_UNITS.workItems,
    unitLabel: reconciliation.unit || work.unit || definition?.primaryUnit.plural || 'work items',
    scope: reconciliation.scope || definition?.scope || null,
    equation: reconciliation.equation || definition?.equation || null,
    total: metricValue(total, valueOptions), accounted: metricValue(accounted, valueOptions),
    unaccounted: metricValue(reconciliation.unaccounted, valueOptions),
    exact: reconciliation.exact === true && !inconsistent,
    source: available ? 'domain_reconciliation' : 'reconciliation',
  }
}

export function canonicalStageViewModels(snapshot, context = {}) {
  if (!snapshot) return null
  const definition = stageDefinition(snapshot.stage)
  const primary = canonicalPrimaryMetric(snapshot, context)
  const domain = snapshot.domain_reconciliation || {}
  const inconsistent = primary.total.state === VALUE_STATES.inconsistent
  const options = {
    executionState: snapshot.state, inconsistent,
    sourceRevision: snapshot.workflow_revision,
    currentRevision: context.workflowRevision ?? snapshot.workflow_revision,
  }
  const counters = Object.entries(domain.buckets || {}).map(([key, value]) => {
    const configured = definition?.counters.find((item) => item.bucket === key)
    const fallbackLabel = String(key).replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
    return { key, label: configured?.label || fallbackLabel,
      unit: configured?.unit || primary.unit, metric: metricValue(value, options) }
  })
  const compact = { stage: snapshot.stage, color: definition?.color || null, primary,
    revision: number(snapshot.revision), workflowRevision: number(snapshot.workflow_revision) }
  const expanded = { ...compact, counters, operational: {
    unit: METRIC_UNITS.workItems,
    counters: ['completed', 'failed', 'skipped', 'processing', 'queued', 'cancelled'].map((key) => ({
      key, metric: metricValue(snapshot.counts?.work_items?.[key], options),
    })),
  }, secondary: {
    // These stay separate and unknown until the canonical snapshot actually supplies them.
    reviewCards: metricValue(snapshot.counts?.review_cards?.total, options),
    changes: metricValue(snapshot.counts?.changes?.verified, options),
  } }
  return { compact, expanded }
}
