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

  it('opens the exact previous revision without interrupting current work', () => {
    const onViewPrevious = vi.fn()
    const container = render({ currentView: 'overview', onReturn: () => {}, onLiveOps: () => {},
      onViewPrevious, workflow: { stage: 'assess', workflow_revision: 2,
        previous_scan_id: 'scan-revision-one', source: 'sharepoint' } })
    const button = [...container.querySelectorAll('button')]
      .find((item) => item.textContent === 'View previous revision')
    expect(button).toBeTruthy()
    act(() => button.click())
    expect(onViewPrevious).toHaveBeenCalledWith('scan-revision-one')
  })

  it('does not offer previous revision for legacy or first-revision work', () => {
    const container = render({ currentView: 'overview', onReturn: () => {}, onLiveOps: () => {},
      onViewPrevious: () => {}, workflow: { stage: 'discover', workflow_revision: 1 } })
    expect(container.textContent).not.toContain('View previous revision')
  })

  it('does not duplicate the status inside its own stage', () => {
    const container = render({ currentView: 'discover', workflow: { stage: 'discover' },
      onReturn: () => {}, onLiveOps: () => {} })
    expect(container.innerHTML).toBe('')
  })

  it('does not stack a generic banner above the persistent remediation card', () => {
    const container = render({ currentView: 'overview', workflow: {
      stage: 'remediate', source: 'sharepoint', running: 8, queued: 62,
    }, onReturn: () => {}, onLiveOps: () => {} })
    expect(container.innerHTML).toBe('')
  })

  it('does not stack a generic banner above the persistent discovery card', () => {
    const container = render({ currentView: 'overview', workflow: {
      stage: 'discover', source: 'sharepoint', running: 1, queued: 0,
    }, onReturn: () => {}, onLiveOps: () => {} })
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
