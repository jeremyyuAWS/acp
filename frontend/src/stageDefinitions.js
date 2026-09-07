/**
 * Presentation and accounting vocabulary for the four user workflow stages.
 *
 * Units are deliberately not interchangeable. In particular, a finding is not a review card or
 * a change, and a processed document is not necessarily a published document.
 */
export const METRIC_UNITS = Object.freeze({
  documents: Object.freeze({ key: 'documents', singular: 'document', plural: 'documents' }),
  findings: Object.freeze({ key: 'findings', singular: 'finding', plural: 'findings' }),
  reviewCards: Object.freeze({ key: 'review_cards', singular: 'review card', plural: 'review cards' }),
  changes: Object.freeze({ key: 'changes', singular: 'change', plural: 'changes' }),
  workItems: Object.freeze({ key: 'work_items', singular: 'work item', plural: 'work items' }),
})

const counter = (key, label, unit, bucket = key) => Object.freeze({ key, label, unit, bucket })

export const STAGE_DEFINITIONS = Object.freeze({
  discover: Object.freeze({
    key: 'discover', label: 'Discover', color: '#2f67b1', primaryUnit: METRIC_UNITS.documents,
    scope: 'discovered inventory',
    equation: 'inventory = sum(lifecycle status buckets)',
    counters: Object.freeze([
      counter('inventory', 'Inventory', METRIC_UNITS.documents, null),
      counter('lifecycle', 'Lifecycle status', METRIC_UNITS.documents, '*'),
    ]),
  }),
  assess: Object.freeze({
    key: 'assess', label: 'Assess', color: '#4f8228', primaryUnit: METRIC_UNITS.documents,
    scope: 'immutable Assess input',
    equation: 'eligible = waiting + processing + assessed + failed + cancelled + skipped',
    counters: Object.freeze([
      counter('waiting', 'Waiting', METRIC_UNITS.documents),
      counter('processing', 'Processing', METRIC_UNITS.documents),
      counter('assessed', 'Assessed', METRIC_UNITS.documents),
      counter('failed', 'Failed', METRIC_UNITS.documents),
      counter('cancelled', 'Stopped manually', METRIC_UNITS.documents),
      counter('skipped', 'Skipped', METRIC_UNITS.documents),
    ]),
  }),
  remediate: Object.freeze({
    key: 'remediate', label: 'Remediate', color: '#76508f', primaryUnit: METRIC_UNITS.findings,
    scope: 'current Remediate execution',
    equation: 'assessed findings = sum(current disposition buckets)',
    counters: Object.freeze([
      counter('resolved_verified', 'Resolved · verified', METRIC_UNITS.findings),
      counter('awaiting_review', 'Awaiting review', METRIC_UNITS.findings),
      counter('approved_pending_verification', 'Approved · awaiting verification', METRIC_UNITS.findings),
      counter('unchanged_no_fix', 'Unchanged · no fix', METRIC_UNITS.findings),
      counter('failed', 'Failed', METRIC_UNITS.findings),
      counter('excluded', 'Excluded', METRIC_UNITS.findings),
      counter('superseded', 'Superseded', METRIC_UNITS.findings),
    ]),
    secondaryUnits: Object.freeze([METRIC_UNITS.reviewCards, METRIC_UNITS.changes]),
  }),
  release: Object.freeze({
    key: 'release', label: 'Release', color: '#a46c0a', primaryUnit: METRIC_UNITS.documents,
    scope: 'immutable Release request',
    equation: 'requested = waiting + processing + published + completed unverified + failed + cancelled + skipped',
    counters: Object.freeze([
      counter('waiting', 'Waiting', METRIC_UNITS.documents),
      counter('processing', 'Processing', METRIC_UNITS.documents),
      counter('published', 'Published · verified', METRIC_UNITS.documents),
      counter('completed_unverified', 'Completed · not verified', METRIC_UNITS.documents),
      counter('failed', 'Failed', METRIC_UNITS.documents),
      counter('cancelled', 'Stopped manually', METRIC_UNITS.documents),
      counter('skipped', 'Skipped', METRIC_UNITS.documents),
    ]),
  }),
})

export const CANONICAL_EXECUTION_STATES = Object.freeze([
  'accepted', 'queued', 'processing', 'paused', 'processing_complete', 'reconciling',
  'succeeded', 'failed', 'cancelled', 'integrity_failed', 'superseded',
])

export const STATE_LABELS = Object.freeze({
  accepted: 'Accepted', queued: 'Waiting', processing: 'Processing', paused: 'Paused',
  processing_complete: 'Processing complete', reconciling: 'Reconciling', succeeded: 'Complete',
  failed: 'Failed', cancelled: 'Stopped manually', integrity_failed: 'Needs attention',
  superseded: 'Superseded',
})

export const ACTION_LABELS = Object.freeze({
  pause: 'Pause', resume: 'Resume', cancel: 'Stop safely', supersede: 'Replace execution',
})

const ACTIONS_BY_STATE = Object.freeze({
  accepted: ['cancel', 'supersede'], queued: ['pause', 'cancel', 'supersede'],
  processing: ['pause', 'cancel', 'supersede'], paused: ['resume', 'cancel', 'supersede'],
})

export function validStageActions(state, { cancelRequested = false, isCurrent = true } = {}) {
  if (!isCurrent || cancelRequested) return []
  return (ACTIONS_BY_STATE[state] || []).map((key) => ({ key, label: ACTION_LABELS[key] }))
}

export function stageDefinition(stage) {
  return STAGE_DEFINITIONS[stage] || null
}
