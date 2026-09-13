import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import WorkflowStageStack from './WorkflowStageStack.jsx'
import { releaseBatchProgress } from './releaseBatchProgress.js'

let root, container
afterEach(() => { if (root) act(() => root.unmount()); container?.remove() })
const snapshot = batch => ({stage:'release',state:'succeeded',execution_id:'incremental-9',workflow_id:'workflow',workflow_revision:1,revision:1,
  reconciliation:{total:1,accounted:1,exact:true},integrity:{ok:true},
  domain_reconciliation:{total:1,accounted:1,unit:'requested documents',exact:true,buckets:{published:1}},
  release_batch_progress:batch})
const batch = {available:true,authorization_id:'approved',run_id:'remediation',total:147,delivered:9,remaining:138,status:'waiting'}

it('shows cumulative authorized delivery without claiming the latest finished request completed the batch', () => {
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container)
  act(() => root.render(<WorkflowStageStack lineage={{scan_id:'scan',workflow_revision:1,stages:[snapshot(batch)]}}/>))
  const summary=container.querySelector('.workflow-stage-stack__summary')
  expect(summary.textContent).toContain('Publishing automatically')
  expect(summary.textContent).toContain('9 of 147 authorized files delivered')
  expect(summary.textContent).not.toContain('Complete')
  expect(container.textContent).toContain('Latest delivery request: 1 of 1 requested documents accounted for')
  expect(container.textContent).toContain('138 authorized files awaiting confirmed delivery')
})

it('never treats the overall scan population as approved scope for a manual or ambiguous request', () => {
  expect(releaseBatchProgress(snapshot({available:false,total:147}))).toBeNull()
  expect(releaseBatchProgress(snapshot({...batch,total:2}))).toBeNull()
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container)
  act(() => root.render(<WorkflowStageStack lineage={{scan_id:'scan',workflow_revision:1,stages:[snapshot(null)]}}/>))
  expect(container.querySelector('.workflow-stage-stack__summary').textContent).toContain('1 of 1 requested documents')
  expect(container.textContent).not.toContain('147')
})

it('keeps stopped delivery visible instead of reviving automatic publication', () => {
  expect(releaseBatchProgress(snapshot({...batch,status:'stopped'}))).toMatchObject({state:'failed',label:'Automatic delivery stopped'})
})
it('does not declare release complete while the authorization is still finalizing reports or packaging', () => {
  expect(releaseBatchProgress(snapshot({...batch,delivered:147,remaining:0,status:'publishing'}))).toMatchObject({state:'processing',label:'Finalizing automatic release'})
})
