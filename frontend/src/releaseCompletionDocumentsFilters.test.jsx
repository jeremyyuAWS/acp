import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Documents from './ReleaseCompletionDocuments.jsx'
afterEach(unmountAll)
const files = [
  {file:'Alpha.docx',remediated_at:'now',compliant:true},
  {file:'Beta.pdf',remediated_at:'now',compliant:false},
  {file:'Gamma.xlsx',compliant:true},
]
const states = [
  {status:'released',label:'Published',reason:'Delivered'},
  {status:'failed',label:'Delivery failed',reason:'Retry available'},
  {status:'ready',label:'Ready to publish',reason:'Saved copy needed'},
]
async function mount(props={}) {
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Documents,{files,states,...props})))
  return {root,container}
}
async function change(element,value) {
  await act(async()=>{
    const proto=element.tagName==='INPUT'?HTMLInputElement.prototype:HTMLSelectElement.prototype
    Object.getOwnPropertyDescriptor(proto,'value').set.call(element,value)
    element.dispatchEvent(new Event(element.tagName==='INPUT'?'input':'change',{bubbles:true}))
  })
}
it('combines filename, publication and verification filters and clears them',async()=>{
  const {container:c}=await mount()
  expect(c.querySelector('[role="status"]').textContent).toBe('3 of 3 documents shown')
  await change(c.querySelector('input'),' BETA ')
  expect([...c.querySelectorAll('tbody th')].map(e=>e.textContent)).toEqual(['Beta.pdf'])
  await change(c.querySelectorAll('select')[0],'failed')
  await change(c.querySelectorAll('select')[2],'passed')
  expect(c.querySelectorAll('tbody tr')).toHaveLength(0)
  expect(c.textContent).toContain('No documents match these filters.')
  await change(c.querySelectorAll('select')[2],'unconfirmed')
  expect(c.querySelectorAll('tbody tr')).toHaveLength(1)
  await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Clear filters').click())
  expect(c.querySelectorAll('tbody tr')).toHaveLength(3)
})
it('preserves selected file queue and clears through its callback',async()=>{
  const onFilter=vi.fn()
  const {container:c}=await mount({filter:'published',onFilter,progressDocuments:[{file:'Alpha.docx',progressState:'published'}]})
  expect(c.querySelectorAll('tbody tr')).toHaveLength(1)
  await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Clear filters').click())
  expect(onFilter).toHaveBeenCalledWith('all')
})
it('retains published copy and retry actions while report introduction remains absent',async()=>{
  const retry=vi.fn()
  const {container:c}=await mount({onRetry:retry,reportSummary:createElement('p',null,'Scan summary and per-file checklists'),
    urls:{'Alpha.docx':'https://example.com/copy'},results:{'Beta.pdf':{status:'failed'}},
    reportsByFile:{'Alpha.docx':createElement('a',{href:'https://example.com/report'},'Download report')}})
  expect(c.querySelector('h3')).toBeNull()
  expect(c.textContent).not.toContain('Scan summary and per-file checklists')
  expect(c.querySelector('a[href="https://example.com/copy"]').textContent).toBe('Open published copy')
  expect(c.textContent).toContain('Download report')
  await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Retry delivery').click())
  expect(retry).toHaveBeenCalledWith(['Beta.pdf'])
  const region=c.querySelector('[aria-label="Publication documents"]')
  expect(region.tabIndex).toBe(0)
  expect(region.className).toBe('release-documents-scroll')
  expect(region.querySelectorAll('thead th[scope="col"]')).toHaveLength(5)
})
it('shows honest verification and an initial empty state',async()=>{
  const {root,container:c}=await mount()
  await change(c.querySelectorAll('select')[2],'unconfirmed')
  expect([...c.querySelectorAll('tbody th')].map(e=>e.textContent)).toEqual(['Beta.pdf','Gamma.xlsx'])
  await act(async()=>root.render(createElement(Documents,{files:[],states:[]})))
  expect(c.textContent).toContain('No documents to show yet.')
})

it('combines file type with publication filters',async()=>{
 const {container:c}=await mount()
 await change(c.querySelector('select[id$="-format"]'),'PDF')
 expect([...c.querySelectorAll('tbody th')].map(e=>e.textContent)).toEqual(['Beta.pdf'])
 expect(c.querySelector('[role="status"]').textContent).toBe('1 of 3 documents shown')
})
it('uses saved-plan scope metadata and hides generic retry for covered copies',async()=>{
 const {container:c}=await mount({coveredFiles:['Beta.pdf'],scopeId:'plan',revision:7,results:{'Beta.pdf':{status:'failed'}},onRetry:vi.fn()})
 expect(c.querySelector('[data-scope-id]').dataset.snapshotRevision).toBe('7')
 expect([...c.querySelectorAll('button')].some(button=>button.textContent==='Retry delivery')).toBe(false)
})
