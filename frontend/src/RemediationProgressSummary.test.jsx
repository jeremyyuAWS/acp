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
  await act(async()=>container.querySelector('.progress-attention').click())
  expect(onSelect).toHaveBeenLastCalledWith('attention')
  await act(async()=>container.querySelector('.remediation-progress-summary-heading button').click())
  expect(onSelect).toHaveBeenLastCalledWith(null)
})
