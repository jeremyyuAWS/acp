import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import AssessApprovalPolicy from './AssessApprovalPolicy.jsx'
const criteria=[{code:'1.1.1',name:'Non-text Content'},{code:'1.3.1',name:'Info and Relationships'}]
it('starts compact and collapsed, with a specific automatic approval summary',()=>{
 const html=renderToStaticMarkup(createElement(AssessApprovalPolicy,{value:{mode:'automatic',review_scs:[]},criteria,formats:['pdf']}))
 const doc=new DOMParser().parseFromString(html,'text/html')
 expect(doc.querySelector('details').hasAttribute('open')).toBe(false)
 expect(doc.querySelector('summary').textContent).toContain('Automatic approval')
 expect(html).toContain('Review proposed fixes')
 expect(html).toContain('does not change assessment scope or automatic publication')
})
it('shows only selected criterion rows and truthful per-format capability labels',()=>{
 const html=renderToStaticMarkup(createElement(AssessApprovalPolicy,{value:{mode:'custom',review_scs:['1.1.1']},criteria,formats:['docx','pdf']}))
 const doc=new DOMParser().parseFromString(html,'text/html')
 expect(doc.querySelectorAll('tbody tr')).toHaveLength(2)
 expect(doc.querySelector('select[aria-label="Approval for 1.1.1"]').value).toBe('review')
 expect(doc.querySelector('select[aria-label="Approval for 1.3.1"]').value).toBe('automatic')
 expect(html).toContain('PDF · Document edit or unsupported target may need you')
})

it('search and review filters only change the displayed rows; bulk choices cover all selected criteria', async () => {
  const { act, useState } = await import('react')
  const { createTestRoot, unmountAll } = await import('./testRoots.js')
  let last
  function Harness(){
    const [policy,setPolicy]=useState({mode:'custom',review_scs:['1.1.1']})
    return createElement(AssessApprovalPolicy,{value:policy,criteria,formats:['pdf'],onChange:value=>{last=value;setPolicy(value)}})
  }
  const {container,root}=createTestRoot()
  try {
    await act(async()=>root.render(createElement(Harness)))
    const search=container.querySelector('input[type="search"]')
    await act(async()=>{
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(search,'relationships')
      search.dispatchEvent(new Event('input',{bubbles:true}))
    })
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    expect(container.querySelector('tbody').textContent).toContain('1.3.1')
    expect(last).toBeUndefined()
    const allReview=[...container.querySelectorAll('button')].find(button=>button.textContent==='All selected review first')
    await act(async()=>allReview.click())
    expect(last).toEqual({mode:'custom',review_scs:['1.1.1','1.3.1']})
    const only=container.querySelector('input[type="checkbox"]')
    await act(async()=>only.click())
    expect(container.querySelector('tbody').textContent).toContain('1.3.1')
    const allAuto=[...container.querySelectorAll('button')].find(button=>button.textContent==='All selected automatic')
    await act(async()=>allAuto.click())
    expect(last).toEqual({mode:'custom',review_scs:[]})
    expect(container.querySelector('tbody').textContent).toContain('No selected criteria match')
    expect(criteria.map(row=>row.code)).toEqual(['1.1.1','1.3.1'])
  } finally {await unmountAll()}
})
