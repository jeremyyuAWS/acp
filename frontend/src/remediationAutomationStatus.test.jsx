import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import Status from './RemediationAutomationStatus.jsx'
it('describes permission separately from repair admission and success', () => {
 const html=renderToStaticMarkup(createElement(Status,{policy:{enabled:true},reviewCount:47}))
 expect(html).toContain('Automatic approval is on')
 expect(html).toContain('47')
 expect(html).toContain('Exceptions remain available for review')
 expect(html).not.toContain('All fixes completed')
})
it('does not infer enabled consent while checking', () => {
 expect(renderToStaticMarkup(createElement(Status,{}))).toContain('Checking permission')
})
it('offers recovery when permission is unavailable', () => {
 const html=renderToStaticMarkup(createElement(Status,{error:'Cannot read setting',onRetry:()=>{}}))
 expect(html).toContain('Setting unavailable')
 expect(html).toContain('Refresh setting')
})
it('collapses both cards by default while concise summaries retain permission and human count',()=>{
 const html=renderToStaticMarkup(createElement(Status,{policy:{enabled:true},reviewCount:2,onOpenReview:()=>{}}))
 expect((html.match(/<details>/g)||[]).length).toBe(2)
 expect(html).not.toContain('<details open')
 expect(html).toContain('2 need your input')
 expect(html).toContain('Open review items')
})
it('native summaries are operable and preserve user expansion across refreshed counts',async()=>{
 const {act}=await import('react')
 const {createTestRoot,unmountAll}=await import('./testRoots.js')
 const {root,container}=createTestRoot()
 try {
  await act(async()=>root.render(createElement(Status,{policy:{enabled:true},reviewCount:2,onOpenReview:()=>{}})))
  const details=container.querySelectorAll('details')
  expect([...details].every(d=>!d.open)).toBe(true)
  await act(async()=>details[1].querySelector('summary').click())
  expect(details[1].open).toBe(true)
  expect(details[1].querySelector('button').textContent).toBe('Open review items')
  await act(async()=>root.render(createElement(Status,{policy:{enabled:true},reviewCount:3,onOpenReview:()=>{}})))
  expect(container.querySelectorAll('details')[1].open).toBe(true)
  expect(container.querySelectorAll('details')[1].querySelector('summary').textContent).toContain('3 need your input')
 } finally {await unmountAll()}
})
