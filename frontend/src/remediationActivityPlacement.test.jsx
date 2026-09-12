import { readFileSync } from 'node:fs'
import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Stack from './WorkflowStageStack.jsx'
import { RemediationActivityPanel } from './RemediationOpsPanel.jsx'
afterEach(unmountAll)
it('keeps one activity feed first in Live and workspace tabs ahead of its run header', () => {
  const app=readFileSync('src/App.jsx','utf8')
  const source=readFileSync('src/Remediate.jsx','utf8')
  expect(app).not.toContain('<RemediationActivityPanel')
  expect(source.match(/<RemediationActivityPanel/g)).toHaveLength(1)
  expect(source.indexOf('<RemediationWorkspaceTabs')).toBeLessThan(source.indexOf('<RemediationRunHeader'))
  const live = source.slice(source.indexOf('live={<>'))
  expect(live.indexOf('<RemediationActivityPanel')).toBeLessThan(live.indexOf('<RemediationRunHeader'))
  expect(live.indexOf('<RemediationActivityPanel')).toBeLessThan(live.indexOf('<RemediationLiveDocuments'))
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

it('retains the generic workflow after-stage slot for future restoration', async () => {
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
