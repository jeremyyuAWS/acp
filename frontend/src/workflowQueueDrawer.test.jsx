import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import Card from './WorkflowStageActivityCard.jsx'
import { getStageProgressQueue } from './api.js'
vi.mock('./api.js', () => ({ getStageProgressQueue: vi.fn() }))
let root, host
afterEach(async () => { if(root) await act(async()=>root.unmount()); root=null; host?.remove(); vi.clearAllMocks() })
const snapshot = (stage='remediate', id='run') => ({ stage, execution_id:id, generated_at:'now',
  domain_reconciliation:stage==='remediate' ? {total:3,accounted:3,exact:true,buckets:{resolved_verified:3}}
    : {total:1,accounted:1,exact:true,buckets:{completed_unverified:1}} })
async function render(data) {
  if(!root) {host=document.createElement('div');document.body.append(host);root=createRoot(host)}
  await act(async()=>root.render(<Card snapshot={data}/>))
}
it('opens the exact finding queue grouped by file and does not navigate', async()=> {
  getStageProgressQueue.mockResolvedValue({execution_id:'run',bucket:'verified',available:true,count:3,
    files:[{file:'a.docx',status:'verified',label:'Verified fixes',findingCount:3}]})
  await render(snapshot())
  const button=host.querySelector('.finding-outcome-kpis__verified')
  button.focus()
  await act(async()=>button.click())
  expect(getStageProgressQueue).toHaveBeenCalledWith('run','verified')
  const drawer=document.querySelector('[role="dialog"]')
  expect(drawer.textContent).toContain('a.docx')
  expect(drawer.textContent).toContain('3 findings')
  expect(drawer.textContent).toContain('1 file')
  await act(async()=>drawer.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})))
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(document.activeElement).toBe(button)
})
it('opens the publication scope and discards a stale response when the run changes', async()=> {
  let resolve
  getStageProgressQueue.mockImplementation(()=>new Promise(r=>resolve=r))
  await render(snapshot('release'))
  await act(async()=>host.querySelector('.workflow-outcome-tiles__tile.tone-green').click())
  expect(document.querySelector('[role="dialog"]').textContent).toContain('this release')
  await render(snapshot('release','next'))
  await act(async()=>resolve({execution_id:'run',bucket:'published',available:true,count:1,files:[{file:'old.pdf'}]}))
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(host.textContent).not.toContain('old.pdf')
})
it('does not substitute a different population when membership disagrees with the tile', async()=> {
  getStageProgressQueue.mockResolvedValue({execution_id:'run',bucket:'verified',available:true,count:99,files:[{file:'other.docx'}]})
  await render(snapshot())
  await act(async()=>host.querySelector('.finding-outcome-kpis__verified').click())
  expect(document.querySelector('[role="dialog"]').textContent).toContain('queue changed')
  expect(document.querySelector('[role="dialog"]').textContent).not.toContain('other.docx')
})
