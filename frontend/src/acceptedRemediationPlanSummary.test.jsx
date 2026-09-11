import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import Summary from './AcceptedRemediationPlanSummary.jsx'
const render = props => renderToStaticMarkup(createElement(Summary, props))
it('formats frozen choices without any editable controls', () => {
  const html = render({ policy: { rule_based: 2, ai: 1, ai_zone: 'any', ai_budget_usd: '2.00', auto_approve_ai: true, document_wide_ai: true }, authorization: { allow_remaining_issues: true } })
  expect(html).toContain('Rules + Cloud AI')
  expect(html).toContain('PDF form-field names, tagged PDF image descriptions, and Word image descriptions')
  expect(html).toContain('$2.00 USD')
  expect(html).toContain('Apply supported suggestions automatically')
  expect(html).toContain('Publish automatically after processing')
  expect(html).not.toMatch(/<input|<button|<select/)
})
it('does not invent absent accepted choices or use owner defaults', () => {
  expect(render({})).toContain('saved choices for this run are unavailable')
  const html = render({ policy: { ai: 0 }, currentPolicy: { rule_based: 2 } })
  expect(html).toContain('Rules only')
  expect(html).toContain('Not recorded')
  expect(html).not.toContain('Apply supported rule-based')
})
it('local plans do not show a cloud spending control', () => {
  const html = render({ policy: { ai: 1, ai_zone: 'local', ai_budget_usd: '0.00', rule_based: 0 }, authorization: { allow_remaining_issues: false } })
  expect(html).toContain('Ollama · Local only')
  expect(html).not.toContain('AI spending limit')
  expect(html).toContain('Review in Release before publishing')
})

it('uses the page font for labels and shared monospace for every saved value', () => {
  const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'accepted-remediation-plan.css'), 'utf8')
  expect(css).toMatch(/\.accepted-remediation-plan dt\s*\{[^}]*font-family: inherit/)
  expect(css).toMatch(/\.accepted-remediation-plan h3\s*\{[^}]*font-family: inherit/)
  expect(css).toMatch(/\.accepted-remediation-plan dd\s*\{[^}]*font-family: var\(--font-mono\)/)
  expect(css).toContain('grid-template-columns: minmax(0, 11rem) minmax(0, 1fr)')
  expect(css).toMatch(/@media \(max-width: 600px\)[\s\S]*grid-template-columns: 1fr/)
  expect(css).not.toContain('minmax(8rem, 1fr)')
})
