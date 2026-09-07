import { describe, expect, it } from 'vitest'
import { canonicalStageCardModel } from './canonicalStageCard.js'
import { canonicalStageViewModels, metricValue, VALUE_STATES } from './stageAccountingModel.js'
import { CANONICAL_EXECUTION_STATES, METRIC_UNITS, STAGE_DEFINITIONS,
  validStageActions } from './stageDefinitions.js'

const snapshot = (stage, domain, extra = {}) => ({
  workflow_revision: 4, revision: 9, stage, state: 'processing', execution_id: `exec-${stage}`,
  counts: { work_items: { unit: 'work items', total: 4, queued: 1, processing: 1,
    completed: 2, failed: 0, cancelled: 0, skipped: 0 } },
  reconciliation: { unit: 'work items', total: 4, accounted: 4, unaccounted: 0, exact: true },
  integrity: { ok: true, affected: [], violations: [] }, control: { cancel_requested: false },
  domain_reconciliation: { total: 4, accounted: 4, unaccounted: 0, exact: true, ...domain },
  ...extra,
})

describe('workflow stage definitions', () => {
  it('has stable colors, primary units, equations, and counters for all four stages', () => {
    expect(Object.keys(STAGE_DEFINITIONS)).toEqual(['discover', 'assess', 'remediate', 'release'])
    expect(Object.values(STAGE_DEFINITIONS).map((stage) => stage.color))
      .toEqual(['#2f67b1', '#4f8228', '#76508f', '#a46c0a'])
    expect(STAGE_DEFINITIONS.discover.primaryUnit).toBe(METRIC_UNITS.documents)
    expect(STAGE_DEFINITIONS.assess.primaryUnit).toBe(METRIC_UNITS.documents)
    expect(STAGE_DEFINITIONS.remediate.primaryUnit).toBe(METRIC_UNITS.findings)
    expect(STAGE_DEFINITIONS.release.primaryUnit).toBe(METRIC_UNITS.documents)
    Object.values(STAGE_DEFINITIONS).forEach((stage) => {
      expect(stage.equation).toBeTruthy()
      expect(stage.counters.length).toBeGreaterThan(0)
    })
    expect(STAGE_DEFINITIONS.remediate.secondaryUnits)
      .toEqual([METRIC_UNITS.reviewCards, METRIC_UNITS.changes])
  })

  it('defines canonical states and only actions accepted by the execution API', () => {
    expect(CANONICAL_EXECUTION_STATES).toContain('processing_complete')
    expect(CANONICAL_EXECUTION_STATES).toContain('integrity_failed')
    expect(validStageActions('processing').map(({ key }) => key))
      .toEqual(['pause', 'cancel', 'supersede'])
    expect(validStageActions('paused').map(({ key }) => key))
      .toEqual(['resume', 'cancel', 'supersede'])
    expect(validStageActions('succeeded')).toEqual([])
    expect(validStageActions('processing', { cancelRequested: true })).toEqual([])
    expect(validStageActions('processing', { isCurrent: false })).toEqual([])
  })
})

describe('canonical accounting display semantics', () => {
  it('does not collapse known zero, unknown, pending, stale, or inconsistent together', () => {
    expect(metricValue(0)).toMatchObject({ state: VALUE_STATES.known, display: '0', value: 0 })
    expect(metricValue(null, { executionState: 'succeeded' }))
      .toMatchObject({ state: VALUE_STATES.unknown, display: 'Not yet available', value: null })
    expect(metricValue(null, { executionState: 'processing' }))
      .toMatchObject({ state: VALUE_STATES.pending, display: 'Calculating…', value: null })
    expect(metricValue(159, { sourceRevision: 11, currentRevision: 12 }))
      .toMatchObject({ state: VALUE_STATES.stale, display: '159 · from revision 11' })
    expect(metricValue(159, { inconsistent: true }))
      .toMatchObject({ state: VALUE_STATES.inconsistent,
        display: 'Accounting temporarily inconsistent', value: 159 })
  })

  it.each([
    ['discover', { unit: 'inventory documents', partitioned: 4,
      equation: 'inventory = sum(lifecycle status buckets)', buckets: { Active: 4 } }, 'documents'],
    ['assess', { unit: 'eligible documents', buckets: { waiting: 1, assessed: 3 } }, 'documents'],
    ['remediate', { unit: 'assessed findings', buckets: { resolved_verified: 2,
      awaiting_review: 2 } }, 'findings'],
    ['release', { unit: 'requested documents', buckets: { published: 3,
      completed_unverified: 1 } }, 'documents'],
  ])('builds matching compact and expanded %s models from one metric', (stage, domain, unit) => {
    const views = canonicalStageViewModels(snapshot(stage, domain))
    expect(views.compact.primary).toBe(views.expanded.primary)
    expect(views.compact.primary.unit.key).toBe(unit)
    expect(views.expanded.counters.every((counter) => counter.unit.key === unit)).toBe(true)
    expect(views.compact.revision).toBe(9)
    expect(views.expanded.revision).toBe(9)
  })

  it('keeps findings, review cards, changes, and operational work items separate', () => {
    const model = canonicalStageViewModels(snapshot('remediate', {
      unit: 'assessed findings', buckets: { resolved_verified: 4 },
    }))
    expect(model.compact.primary.unit).toBe(METRIC_UNITS.findings)
    expect(model.expanded.operational.unit).toBe(METRIC_UNITS.workItems)
    expect(model.expanded.secondary.reviewCards.state).toBe(VALUE_STATES.pending)
    expect(model.expanded.secondary.changes.state).toBe(VALUE_STATES.pending)
    expect(model.expanded.secondary.reviewCards.value).toBeNull()
    expect(model.expanded.secondary.changes.value).toBeNull()
  })

  it('exposes the integration API through the existing card model', () => {
    const model = canonicalStageCardModel(snapshot('assess', {
      unit: 'eligible documents', buckets: { assessed: 4 },
    }))
    expect(model.stageColor).toBe(STAGE_DEFINITIONS.assess.color)
    expect(model.actions.map(({ key }) => key)).toEqual(['pause', 'cancel', 'supersede'])
    expect(model.compact.primary).toBe(model.expanded.primary)
  })
})
