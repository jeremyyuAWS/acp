import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
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
const here = dirname(fileURLToPath(import.meta.url))

describe('canonical stage card', () => {
  it('renders the server-authored equation with an explicit unit and revisions', () => {
    expect(canonicalStageCardModel(SNAPSHOT).workItems).toEqual([
      ['Completed', 5], ['Failed', 1], ['Skipped', 1], ['Processing', 1],
      ['Waiting', 2], ['Stopped manually', 0],
    ])
    const html = render(SNAPSHOT)
    expect(html).toContain('Integrity check: 10 of 10 work items accounted for')
    expect(html).toContain('Completed</dt><dd')
    expect(html).toContain('>5</dd>')
    expect(html).toContain('Failed</dt><dd')
    expect(html).toContain('Skipped</dt><dd')
    expect(html).toContain('Processing</dt><dd')
    expect(html).toContain('Waiting</dt><dd')
    expect(html).toContain('Workflow revision 3 · snapshot revision 12')
    expect(html).toContain('execution-1')
    expect(html).toContain('Not yet sealed')
  })

  it('never turns unknown totals into zero', () => {
    const html = render({ ...SNAPSHOT, counts: { work_items: { unit: 'work items', total: null } },
      reconciliation: { unit: 'work items', total: null, accounted: null, unaccounted: null } })
    expect(html).toContain('Integrity check: Not reported of Not reported work items')
    expect(html).not.toContain('0 of 0')
    expect(html).toContain('Completed</dt><dd')
    expect(html).toContain('>Not reported</dd>')
  })

  it('withholds the reconciled claim when integrity fails', () => {
    const html = render({ ...SNAPSHOT, integrity: { ok: false, affected: ['work_item_partition'] },
      reconciliation: { ...SNAPSHOT.reconciliation, exact: false, unaccounted: -1 } })
    expect(html).toContain('Accounting temporarily inconsistent.')
    expect(html).not.toContain('10 of 10 work items accounted for')
    expect(html).not.toContain('aria-label="Release work-item counts"')
  })

  it('distinguishes a requested stop, a completed stop, and failure', () => {
    expect(canonicalStageCardModel({ ...SNAPSHOT,
      control: { cancel_requested: true } }).stateLabel).toBe('Stopping safely')
    expect(canonicalStageCardModel({ ...SNAPSHOT, state: 'cancelled',
      control: { cancel_requested: true } }).stateLabel).toBe('Stopped manually')
    expect(canonicalStageCardModel({ ...SNAPSHOT, state: 'failed' }).stateLabel).toBe('Failed')
  })

  it('keeps the canonical partition visible while leased work drains after a stop request', () => {
    const html = render({ ...SNAPSHOT, control: { cancel_requested: true } })
    expect(html).toContain('Release · Stopping safely')
    expect(html).toContain('Processing</dt><dd')
    expect(html).toContain('>1</dd>')
    expect(html).toContain('Waiting</dt><dd')
    expect(html).toContain('>2</dd>')
  })

  it('does not equate completed work items with resolved findings', () => {
    const html = render({ ...SNAPSHOT, state: 'succeeded',
      sealed_output: { manifest_id: 'manifest-1' } })
    expect(html).toContain('Release · Complete')
    expect(html).toContain('manifest-1')
    expect(html).toContain('does not mean every accessibility finding was resolved')
    expect(html).not.toContain('all findings resolved')
  })

  it.each([
    ['discover', {
      unit: 'inventory documents', scope: 'discovered inventory',
      equation: 'inventory = sum(lifecycle status buckets)', total: 24, partitioned: 24,
      unaccounted: 0, exact: true, buckets: { Active: 20, 'Archive Candidate': 4 },
    }, ['24 of 24 inventory documents reconciled', 'Active</dt><dd', '>20</dd>', 'Archive Candidate</dt><dd']],
    ['assess', {
      unit: 'eligible documents', scope: 'immutable Assess input',
      equation: 'eligible = waiting + processing + assessed + failed + cancelled + skipped',
      total: 10, accounted: 10, unaccounted: 0, exact: true,
      buckets: { waiting: 1, processing: 2, assessed: 5, failed: 1, cancelled: 1, skipped: 0 },
    }, ['10 of 10 eligible documents reconciled', 'Assessed</dt><dd', 'Stopped manually</dt><dd']],
    ['remediate', {
      unit: 'assessed findings', scope: 'current Remediate execution',
      equation: 'assessed findings = sum(current disposition buckets)',
      total: 9, accounted: 9, unaccounted: 0, exact: true,
      buckets: { resolved_verified: 5, awaiting_review: 2, failed: 1, excluded: 1 },
    }, ['9 of 9 assessed findings reconciled', 'Resolved · verified</dt><dd', 'Awaiting review</dt><dd']],
    ['release', {
      unit: 'requested documents', scope: 'immutable Release request',
      equation: 'requested = waiting + processing + published + completed unverified + failed + cancelled + skipped',
      total: 8, accounted: 8, unaccounted: 0, exact: true,
      buckets: { waiting: 1, processing: 0, published: 5, completed_unverified: 1,
        failed: 0, cancelled: 1, skipped: 0 },
    }, ['8 of 8 requested documents reconciled', 'Published · verified</dt><dd',
      'Completed · not verified</dt><dd', 'Stopped manually</dt><dd']],
  ])('uses %s domain accounting as the primary stage story', (stage, domain, expected) => {
    const html = render({ ...SNAPSHOT, stage, domain_reconciliation: domain })
    expected.forEach((text) => expect(html).toContain(text))
    expect(html).toContain(`Integrity check: ${domain.equation}`)
    expect(html).toContain('Operational work-item progress')
    expect(html).toContain(`aria-label="${stage[0].toUpperCase()}${stage.slice(1)} work-item counts"`)
  })

  it('withholds operational substitutions when domain accounting is incomplete', () => {
    const html = render({ ...SNAPSHOT, domain_reconciliation: {
      unit: 'requested documents', scope: 'immutable Release request',
      equation: 'requested = sum(document outcomes)', total: null, accounted: null,
      unaccounted: null, exact: false, buckets: { published: null, failed: null },
    } })
    expect(html).toContain('Accounting temporarily inconsistent.')
    expect(html.match(/class="machine-value"/g)).toHaveLength(3)
    expect(html).not.toContain('10 of 10 requested documents')
    expect(html).not.toContain('Operational work-item progress')
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

  it('shows the furthest pipeline stage when every stage is terminal', () => {
    const stage = currentCanonicalStage({ stages: [
      { stage: 'release', state: 'cancelled', revision: 2,
        last_durable_update_at: '2026-09-07T01:00:00Z' },
      { stage: 'discover', state: 'succeeded', revision: 8,
        last_durable_update_at: '2026-09-07T01:04:00Z' },
      { stage: 'remediate', state: 'succeeded', revision: 6,
        last_durable_update_at: '2026-09-07T01:03:00Z' },
    ] })
    expect(stage.stage).toBe('release')
  })
})

describe('app-level canonical ownership', () => {
  it('keeps one lineage hook and card alive outside the tab panel', () => {
    const app = readFileSync(join(here, 'App.jsx'), 'utf8')
    const hook = app.indexOf('useCanonicalStageLineage(')
    const signIn = app.search(/^ {2}if \(!me\) return <SignIn/m)
    const card = app.indexOf('<CanonicalStageCard')
    const panel = app.indexOf('id="workflow-panel"')
    expect(hook).toBeGreaterThan(-1)
    expect(hook).toBeLessThan(signIn)
    expect(card).toBeGreaterThan(-1)
    expect(card).toBeLessThan(panel)
  })

  it('deduplicates the richer remediation card and the canonical Release fallback', () => {
    const app = readFileSync(join(here, 'App.jsx'), 'utf8')
    expect(app).toContain("canonicalStage.stage !== 'remediate'")
    expect(app).toContain("canonicalAvailable={canonicalStage?.stage === 'release'}")
    expect(app).toContain("{ release: 'publish', assess: 'assess', discover: 'discover' }")
  })
})
