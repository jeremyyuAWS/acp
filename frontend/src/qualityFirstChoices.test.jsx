import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot } from './testRoots.js'
import RemediationPlanChoices from './RemediationPlanChoices.jsx'
import WorkflowStageStack from './WorkflowStageStack.jsx'

it('offers a distinct opt-in without selecting it for existing cloud plans', async () => {
  const {container, root} = createTestRoot()
  const onChange = vi.fn()
  await act(async () => root.render(<RemediationPlanChoices policy={{ai:1,ai_zone:'any'}} budgetSupported onChange={onChange} />))
  const label = [...container.querySelectorAll('label')].find(el => el.textContent.includes('Quality-first'))
  expect(label.querySelector('input').checked).toBe(false)
  await act(async () => label.querySelector('input').click())
  expect(onChange).toHaveBeenCalledWith('ai_mode', 'quality')
  await act(async () => root.unmount())
})

const stages = ['discover','assess','remediate','release']
describe.each(stages)('%s workflow disclosure', stage => {
  it.each([stage, 'another-tab', null])('only opens running work on its own tab (%s)', async activeStage => {
    const {container, root} = createTestRoot()
    const lineage = {workflow_id:'tabs',workflow_revision:1, stages:[{
      stage, state:'processing', execution_id:'run', revision:1, workflow_revision:1,
      integrity:{ok:true}, counts:{work_items:{total:2,processing:1,queued:1}},
    }]}
    await act(async () => root.render(<WorkflowStageStack lineage={lineage} activeStage={activeStage} />))
    expect(container.querySelector('.workflow-stage-stack__summary').getAttribute('aria-expanded')).toBe(String(activeStage === stage))
    expect(container.querySelector('.workflow-stage-stack__state').textContent).toBeTruthy()
    if(activeStage !== stage) expect(container.querySelector('.workflow-stage-stack__summary .live-heartbeat-bars')).not.toBeNull()
    await act(async () => root.render(<WorkflowStageStack lineage={lineage} activeStage={stage} />))
    expect(container.querySelector('.workflow-stage-stack__body').hidden).toBe(false)
    await act(async () => root.render(<WorkflowStageStack lineage={lineage} activeStage={null} />))
    expect(container.querySelector('.workflow-stage-stack__body').hidden).toBe(true)
    await act(async () => root.unmount())
  })
})

it('deliberately omits the shared stage stack on Overview without deleting its implementation', () => {
  const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'App.jsx'), 'utf8')
  expect(app).toContain("{view !== 'overview' && <WorkflowStageStack")
})
