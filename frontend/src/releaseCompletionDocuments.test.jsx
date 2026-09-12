import { expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ReleaseCompletionDocuments from './ReleaseCompletionDocuments.jsx'
it('keeps saved, verified, and delivered evidence separate', () => {
  const html = renderToStaticMarkup(createElement(ReleaseCompletionDocuments, {
    files:[{ file:'a.docx', remediated_at:'2026-09-11', compliant:false }],
    states:[{ status:'ready', label:'Ready with remaining issues', reason:'Remaining issues recorded' }],
  }))
  expect(html).toContain('Saved in ACP')
  expect(html).toContain('Not confirmed clear')
  expect(html).toContain('Ready with remaining issues')
  expect(html).not.toContain('Open published copy')
})
