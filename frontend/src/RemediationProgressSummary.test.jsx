import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import RemediationProgressSummary from './RemediationProgressSummary.jsx'
let root, container
afterEach(async()=> { if(root) await act(async()=>root.unmount());container?.remove() })
async function mount(props) { container=document.createElement('div');document.body.append(container);root=createRoot(container);await act(async()=>root.render(<RemediationProgressSummary {...props}/>)); }
it('partitions recorded stages and reports unknown progress instead of guessing', async () => {
  await mount({documents:[{file:'a',progressState:'verified'},{file:'b',progressState:'published'},{file:'c'}]})
  expect(container.textContent).toContain('1 document awaiting confirmed progress.')
  expect(container.querySelector('.progress-verified strong').textContent).toBe('1')
  expect(container.querySelector('.progress-ready strong').textContent).toBe('0')
  expect(container.querySelector('.progress-published strong').textContent).toBe('1')
})
it('makes counts accessible filters and supports clearing selection', async () => {
  const onSelect=vi.fn()
  await mount({documents:[{file:'a',progressState:'processing'}],selected:'processing',onSelect})
  expect(container.querySelector('.progress-processing').getAttribute('aria-pressed')).toBe('true')
  expect(container.querySelector('.progress-processing').getAttribute('aria-label')).toBe('Show documents: Processing (1)')
  expect(container.textContent).toContain('Select a status to filter the document list below.')
  expect(container.textContent).toContain('Showing processing documents: 1 of 1.')
  expect(container.querySelector('.remediation-progress-summary-heading button').textContent).toBe('Show all 1 document')
  await act(async()=>container.querySelector('.progress-attention').click())
  expect(onSelect).toHaveBeenLastCalledWith('attention')
  await act(async()=>container.querySelector('.remediation-progress-summary-heading button').click())
  expect(onSelect).toHaveBeenLastCalledWith(null)
})
it('clearly labels the all-documents reset and current view', async () => {
  await mount({documents:Array.from({length:32},(_,i)=>({file:String(i),progressState:'attention'})),onSelect:vi.fn()})
  expect(container.querySelector('.remediation-progress-summary-heading button').textContent).toBe('Show all 32 documents')
  expect(container.textContent).toContain('Showing all 32 documents.')
  expect(container.querySelector('.progress-attention').textContent).toContain('Filter document list')
})
it('hides only Release document attention while retaining Remediate attention', async () => {
 const documents=[{file:'a',progressState:'attention'}]
 await mount({documents,variant:'release',onSelect:vi.fn()})
 expect(container.querySelector('.progress-attention')).toBeNull()
 expect(container.querySelectorAll('.remediation-progress-summary-counts button')).toHaveLength(4)
 await act(async()=>root.render(<RemediationProgressSummary documents={documents} onSelect={()=>{}}/>))
 expect(container.querySelector('.progress-attention').textContent).toContain('Needs attention')
})
