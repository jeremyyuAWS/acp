import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import Outcomes from './DocumentWideAiOutcomes.jsx'
it('shows saved suggestions and useful exception reasons without claiming fixes', () => {
  const html = renderToStaticMarkup(createElement(Outcomes, { snapshot: { enabled: true, complete: true, files: [{ file: 'a.docx', suggestions: 2, status: 'generated', reasons: ['insufficient_visual_evidence', 'ambiguous_locator'] }] } }))
  expect(html).toContain('2 suggestions')
  expect(html).toContain('did not guess a description')
  expect(html).toContain('one exact place to change')
  expect(html).toContain('not applied or verified fixes')
})
it('does not render for runs without opt-in', () => {
  expect(renderToStaticMarkup(createElement(Outcomes, {}))).toBe('')
})
it('distinguishes missing retained results and partial history', () => {
  const html = renderToStaticMarkup(createElement(Outcomes, { snapshot: { enabled: true, complete: false, files: [] } }))
  expect(html).toContain('most recent retained activity')
  expect(html).toContain('No document-wide result has been recorded')
})
