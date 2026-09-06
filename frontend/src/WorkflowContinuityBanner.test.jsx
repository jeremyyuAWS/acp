// @vitest-environment jsdom
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import WorkflowContinuityBanner, { primaryActiveWorkflow, workflowRevisionLabel } from './WorkflowContinuityBanner'

afterEach(unmountAll)

function render(props) {
  const { container, root } = createTestRoot()
  act(() => root.render(createElement(WorkflowContinuityBanner, props)))
  return container
}

describe('workflow continuity', () => {
  it('prefers the freshest workflow and downstream stage on a tie', () => {
    const items = [
      { stage: 'discover', updated_at: '2026-09-05T10:00:00Z' },
      { stage: 'remediate', updated_at: '2026-09-05T10:00:00Z' },
      { stage: 'assess', updated_at: '2026-09-05T09:00:00Z' },
      { stage: 'publish', updated_at: '2026-09-05T10:00:00Z' },
    ]
    expect(primaryActiveWorkflow(items).stage).toBe('publish')
  })

  it('returns to existing work without presenting a start action', () => {
    const onReturn = vi.fn()
    const container = render({ currentView: 'overview', onReturn, onLiveOps: () => {},
      workflow: { stage: 'assess', source: 'sharepoint', workflow_revision: 3, running: 2, queued: 12 } })
    expect(container.textContent).not.toMatch(/start/i)
    expect(container.textContent).toContain('Workflow revision 3')
    expect(container.querySelector('button').textContent).toBe('Continue current Assessment')
    act(() => container.querySelector('button').click())
    expect(onReturn).toHaveBeenCalledWith('assess')
  })

  it('uses revision one for legacy active-workflow responses', () => {
    expect(workflowRevisionLabel({})).toBe('Workflow revision 1')
  })

  it('does not duplicate the status inside its own stage', () => {
    const container = render({ currentView: 'discover', workflow: { stage: 'discover' },
      onReturn: () => {}, onLiveOps: () => {} })
    expect(container.innerHTML).toBe('')
  })

  it('names active publishing as Release', () => {
    const container = render({ currentView: 'overview', workflow: {
      stage: 'publish', source: 'sharepoint', running: 1, queued: 8,
    }, onReturn: () => {}, onLiveOps: () => {} })
    expect(container.textContent).toContain('Release is still running')
    expect(container.querySelector('button').textContent).toContain('Release')
  })
})
