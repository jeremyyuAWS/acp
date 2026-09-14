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
  expect(html).toContain('Needs verification')
  expect(html).toContain('Remaining findings or incomplete checks.')
  expect(html).not.toContain('Not confirmed clear')
  expect(html).toContain('Ready with remaining issues')
  expect(html).not.toContain('Open published copy')
})

it('does not present saving or publishing as a passed accessibility check', () => {
  const html = renderToStaticMarkup(createElement(ReleaseCompletionDocuments, {
    files: [{ file: 'published.docx', remediated_at: '2026-09-13', compliant: false }, { file: 'pending.docx', compliant: true }, { file: 'passed.docx', remediated_at: '2026-09-13', compliant: true }],
    states: [{ status: 'released', label: 'Published' }],
  }))
  expect(html.match(/<td>Needs verification/g)).toHaveLength(2)
  expect(html.match(/<td>Selected checks passed/g)).toHaveLength(1)
  expect(html).not.toContain('Not confirmed clear')
})
