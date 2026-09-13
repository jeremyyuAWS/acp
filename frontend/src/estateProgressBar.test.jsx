import { it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import EstateProgressPanel from './EstateProgressPanel.jsx'

it('does not paint completed progress when no estate documents are remediated', () => {
  const html = renderToStaticMarkup(createElement(EstateProgressPanel, {
    inventory: { discovered: 147, assessment_eligible: 147 }, analysed: 147, certifiable: 0,
  }))
  const stage = html.slice(html.indexOf('>Remediated<'))
  expect(stage).toContain('width:0%')
  expect(stage).not.toContain('width:52%')
})
