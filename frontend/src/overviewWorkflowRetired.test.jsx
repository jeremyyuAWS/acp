import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync, readdirSync } from 'node:fs'
import Overview from './Overview.jsx'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Owner explicitly retired the entire disclosure, including its nested panels, on 2026-09-14.
describe('Overview workflow panels are intentionally retired', () => {
  it.each([false, true])('omits the legacy UI while preserving balanced charts (assessed=%s)', assessed => {
    const files = [{ file: 'example.pdf', type: 'PDF', status: assessed ? 'done' : 'discovered', score: assessed ? 80 : null, issues: [] }]
    const run = { id: 'retirement', status: 'done', files: 1, scope: { inventory: { discovered: 1, assessment_eligible: 1, by_format: { pdf: 1 } } } }
    const html = renderToStaticMarkup(createElement(Overview, { run, files }))
    expect(html).not.toContain('Workflow and assessment details')
    for (const id of ['estate-progress', 'assessment-summary', 'next-step']) expect(html).not.toContain(`data-accordion="${id}"`)
    for (const title of ['Estate coverage by file type', 'Document formats', 'Remediation opportunities', 'Finding categories', 'Human review age', 'Report exports']) expect(html).toContain(title)
  })
  it('preserves the retired component without any application mount', () => {
    const dir = dirname(fileURLToPath(import.meta.url))
    const retired = readFileSync(join(dir, 'RetiredOverviewWorkflow.jsx'), 'utf8')
    expect(retired).toContain('<EstateProgressPanel')
    expect(retired).toContain('<NextStep')
    expect(retired).toContain('id="assessment-summary"')
    for (const file of readdirSync(dir).filter(file => file.endsWith('.jsx') && !file.includes('.test.'))) {
      const source = readFileSync(join(dir, file), 'utf8')
      expect(source, file).not.toMatch(/<RetiredOverviewWorkflow\b/)
      if (file !== 'RetiredOverviewWorkflow.jsx') {
        expect(source, file).not.toMatch(/<EstateProgressPanel\b/)
        expect(source, file).not.toMatch(/<NextStep\b/)
      }
    }
  })
})
