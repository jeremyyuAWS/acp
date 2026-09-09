import { createElement, act } from 'react'
import { describe, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import WorkflowStageStack from './WorkflowStageStack.jsx'
import { assessmentStageActivity } from './assessmentStageActivity.js'
const snapshot = {
  stage: 'assess', scan_id: 'scan-1', execution_id: 'assess-1', workflow_revision: 1,
  state: 'succeeded', revision: 4,
  domain_reconciliation: { total: 39, accounted: 39, exact: true,
    unit: 'eligible documents', buckets: { assessed: 16, processing: 12, waiting: 11 } },
}
const lineage = { scan_id: 'scan-1', workflow_revision: 1, stages: [snapshot] }
describe('assessment header and runner completion', () => {
  it('reproduces a completed coordinator with 16 results while the runner has 28, then completes together', async () => {
    const { root, container } = createTestRoot()
    const show = async (phase, completed) => act(async () => root.render(createElement(WorkflowStageStack, {
      lineage, assessmentActivity: { runId: 'scan-1', executionId: 'assess-1', phase, completed, total: 39 },
      stageDetails: { assess: createElement('p', null, phase === 'done' ? 'Assessment results' : 'Assessing now') },
    })))
    await show('running', 28)
    const summary = () => container.querySelector('.workflow-stage-stack__summary')
    expect(summary().textContent).toContain('Assessing')
    expect(summary().textContent).toContain('28 assessed of 39')
    expect(summary().textContent).not.toContain('Complete')
    expect(summary().textContent).not.toContain('✓')
    await show('done', 39)
    expect(summary().textContent).toContain('Complete')
    expect(summary().textContent).toContain('39 assessed of 39')
    expect(summary().textContent).toContain('✓')
    await act(async () => unmountAll())
  })
  it('does not claim completion while canonical documents are pending before the runner resumes', () => {
    expect(assessmentStageActivity(snapshot, null, 'scan-1').state).toBe('processing')
  })
  it('does not apply a prior completed run to a new execution on the same scan', () => {
    const newer = { ...snapshot, execution_id: 'new-assess-2',
      domain_reconciliation: { ...snapshot.domain_reconciliation,
        buckets: { assessed: 0, waiting: 39, processing: 0 } } }
    const stale = { runId: 'scan-1', executionId: 'assess-1', phase: 'done', completed: 39, total: 39 }
    expect(assessmentStageActivity(newer, stale, 'scan-1')).toEqual({ state: 'processing', label: 'Assessing' })
    expect(assessmentStageActivity(newer, { ...stale, executionId: null }, 'scan-1'))
      .toEqual({ state: 'processing', label: 'Assessing' })
  })

  it('ignores another scan and preserves cancellation or failure', () => {
    const activity = { runId: 'other-scan', phase: 'done', completed: 39, total: 39 }
    expect(assessmentStageActivity(snapshot, activity, 'scan-1').state).toBe('processing')
    expect(assessmentStageActivity({ ...snapshot, state: 'failed' }, { ...activity, runId: 'scan-1' })).toBeNull()
    expect(assessmentStageActivity({ ...snapshot, state: 'cancelled' }, { ...activity, runId: 'scan-1' })).toBeNull()
  })
})
