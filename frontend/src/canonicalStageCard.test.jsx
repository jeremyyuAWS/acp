import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import CanonicalStageCard from './CanonicalStageCard.jsx'
import { canonicalStageCardModel, currentCanonicalStage } from './canonicalStageCard.js'

const SNAPSHOT = {
  workflow_id: 'workflow-1', workflow_revision: 3, stage: 'release',
  execution_id: 'execution-1', revision: 12, state: 'processing',
  last_durable_update_at: '2026-09-07T01:02:03+00:00',
  counts: { work_items: { unit: 'work items', total: 10, queued: 2, processing: 1,
    completed: 5, failed: 1, cancelled: 0, skipped: 1 } },
  reconciliation: { unit: 'work items', total: 10, accounted: 10, unaccounted: 0, exact: true },
  integrity: { ok: true, affected: [], violations: [] },
  control: { cancel_requested: false },
  sealed_output: null,
}

const render = (snapshot) => renderToStaticMarkup(createElement(CanonicalStageCard, { snapshot }))

describe('canonical stage card', () => {
  it('renders the server-authored equation with an explicit unit and revisions', () => {
    const html = render(SNAPSHOT)
    expect(html).toContain('10 of 10 work items accounted for')
    expect(html).toContain('Workflow revision 3 · snapshot revision 12')
    expect(html).toContain('execution-1')
    expect(html).toContain('Not yet sealed')
  })

  it('never turns unknown totals into zero', () => {
    const html = render({ ...SNAPSHOT, counts: { work_items: { unit: 'work items', total: null } },
      reconciliation: { unit: 'work items', total: null, accounted: null, unaccounted: null } })
    expect(html).toContain('Not reported of Not reported work items')
    expect(html).not.toContain('0 of 0')
  })

  it('withholds the reconciled claim when integrity fails', () => {
    const html = render({ ...SNAPSHOT, integrity: { ok: false, affected: ['work_item_partition'] },
      reconciliation: { ...SNAPSHOT.reconciliation, exact: false, unaccounted: -1 } })
    expect(html).toContain('Accounting temporarily inconsistent.')
    expect(html).not.toContain('10 of 10 work items accounted for')
  })

  it('distinguishes a requested stop, a completed stop, and failure', () => {
    expect(canonicalStageCardModel({ ...SNAPSHOT,
      control: { cancel_requested: true } }).stateLabel).toBe('Stopping')
    expect(canonicalStageCardModel({ ...SNAPSHOT, state: 'cancelled',
      control: { cancel_requested: true } }).stateLabel).toBe('Stopped')
    expect(canonicalStageCardModel({ ...SNAPSHOT, state: 'failed' }).stateLabel).toBe('Failed')
  })

  it('does not equate completed work items with resolved findings', () => {
    const html = render({ ...SNAPSHOT, state: 'succeeded',
      sealed_output: { manifest_id: 'manifest-1' } })
    expect(html).toContain('Release · Complete')
    expect(html).toContain('manifest-1')
    expect(html).toContain('does not mean every accessibility finding was resolved')
    expect(html).not.toContain('all findings resolved')
  })
})

describe('current canonical stage selection', () => {
  it('prefers active work over a newer terminal stage', () => {
    const stage = currentCanonicalStage({ stages: [
      { stage: 'assess', state: 'processing', revision: 4, last_durable_update_at: '2026-09-07T01:00:00Z' },
      { stage: 'discover', state: 'succeeded', revision: 8, last_durable_update_at: '2026-09-07T01:02:00Z' },
    ] })
    expect(stage.stage).toBe('assess')
  })
})
