import { readFileSync } from 'node:fs'
import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Stack from './WorkflowStageStack.jsx'
import { RemediationActivityPanel } from './RemediationOpsPanel.jsx'
afterEach(unmountAll)
it('keeps one activity feed after the workflow remediation card and delivery closed by default', () => {
  const app=readFileSync('src/App.jsx','utf8')
  const source=readFileSync('src/Remediate.jsx','utf8')
  expect(app).toContain("stageAfter={{remediate: view === 'remediate' && isVisible(access, 'remediate')")
  expect(app.match(/<RemediationActivityPanel/g)).toHaveLength(1)
  expect(source).not.toContain('<RemediationActivityPanel')
  expect(source).toContain('<details className="panel" aria-label="Publish corrected copies">')
  expect(source).toContain('<RemediationOpsPanel streamlined hideActivity')
})
it('animates the current document row again when a new saved lead event arrives', async () => {
  const {container,root}=createTestRoot()
  const props={snapshot:{batch_id:'batch',state:'processing',terminal:false},connected:true,receivedAt:Date.now()}
  const first={key:'one',file:'file.pdf',line:'Saved corrected copy',tone:'success'}
  await act(async()=>root.render(<RemediationActivityPanel {...props} events={[first]} />))
  const row=container.querySelector('ol > li')
  await act(async()=>root.render(<RemediationActivityPanel {...props} events={[{...first,key:'two',line:'Fix independently verified'}]} />))
  expect(container.querySelector('ol > li')).not.toBe(row)
  expect(container.textContent).toContain('Fix independently verified')
})

it('renders activity immediately after Remediate even when the stage is collapsed and before Release', async () => {
  const {container,root}=createTestRoot()
  const lineage={scan_id:'scan',workflow_revision:1,stages:[
    {stage:'remediate',execution_id:'r',workflow_revision:1,state:'succeeded'},
    {stage:'release',execution_id:'p',workflow_revision:1,state:'succeeded'}]}
  await act(async()=>root.render(<Stack lineage={lineage} stageAfter={{remediate:<div>Visible feed</div>}} />))
  const feed=container.querySelector('[data-stage-after="remediate"]')
  expect(feed.textContent).toBe('Visible feed')
  expect(feed.closest('[hidden]')).toBeNull()
  expect([...container.querySelectorAll('.workflow-stage-stack__stage')].map(n=>n.dataset.stage)).toBeDefined()
  expect(feed.parentElement.textContent).toContain('Remediate')
  expect(feed.parentElement.nextElementSibling.textContent).toContain('Release')
})
