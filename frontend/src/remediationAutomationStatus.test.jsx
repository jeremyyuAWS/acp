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
