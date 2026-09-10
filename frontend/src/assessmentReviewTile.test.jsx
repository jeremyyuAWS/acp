import { act, createElement, useState } from 'react'
import { afterEach, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import AssessSummary from './AssessSummary.jsx'
import RemediationWorkspaceTabs from './RemediationWorkspaceTabs.jsx'
import { remediationReviewCounts } from './remediationCountSummary.js'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(() => { unmountAll(); history.replaceState({}, '', '/') })
const files = Array.from({ length: 58 }, (_, index) => ({ file: `document-${index}.docx`, status: 'analysed',
  issues: Array.from({ length: index === 57 ? 79 : 42 }, () => ({ wcag: 'SC_1_1_1', severity: 'SERIOUS' })),
}))
const rows = Array.from({ length: 119 }, (_, index) => ({ id: `item-${index}`, file: files[index % 58].file,
  rule_id: ['1.1.1', '2.4.4', '1.4.5'][Math.floor(index / 58)], hasProposal: true, after: 'Generated suggestion',
  _raw: { finding_count: index === 118 ? 2 : 13 },
}))
const props = { files, criteria: new Set(['1.1.1']), cap: { docx: { '1.1.1': 'assisted' } },
  assessment: { docx: { '1.1.1': 'auto' } }, remediationForecast: { automatic: 937, human: 1536 } }
function Workspace({ items }) {
  const counts = remediationReviewCounts(items)
  const [request, setRequest] = useState(null)
  return createElement(RemediationWorkspaceTabs, {
    runId: 'scan-119', snapshot: { scan_id: 'scan-119', batch_id: 'batch-119' }, reviewCount: counts.pendingItems, workspaceRequest: request,
    plan: createElement(AssessSummary, { ...props, reviewSummary: counts,
      onOpenReview: () => setRequest({ mode: 'review' }) }),
    review: 'Current review items',
  })
}
const tile = container => [...container.querySelectorAll('button')].find(el => el.textContent.startsWith('Review queue items'))
const reviewTab = container => container.querySelector('#rem-mode-review')

it('explains 119 review items as grouped findings and links to the same Review tab', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Workspace, { items: rows })))
  expect(reviewTab(container).textContent).toBe('Review119')
  expect(tile(container).textContent).toContain('Review queue items119')
  expect(tile(container).textContent).toContain('1,536 findings grouped into 119 review items across 58 documents')
  expect(tile(container).textContent).toContain('same criterion within one document')
  expect(tile(container).textContent).toContain('Plan previews count individual findings instead')
  expect(container.textContent).toContain('Total findings2473')
  await act(async () => tile(container).click())
  expect(reviewTab(container).getAttribute('aria-selected')).toBe('true')
  expect(container.querySelector('#rem-panel-review').hidden).toBe(false)
  expect(container.querySelector('dialog').open).toBe(false)
})

it('updates the tile and tab together after a decision; zero is a queue state, not a completion claim', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Workspace, { items: rows })))
  await act(async () => root.render(createElement(Workspace, { items: rows.map((row, i) => i ? row : { ...row, status: 'approved' }) })))
  expect(reviewTab(container).textContent).toBe('Review118')
  expect(tile(container).textContent).toContain('Review queue items118')
  expect(tile(container).textContent).toContain('1,523 findings')
  await act(async () => root.render(createElement(Workspace, { items: [] })))
  expect(reviewTab(container).textContent).toBe('Review0')
  expect(tile(container).textContent).toContain('Review queue items0')
  expect(tile(container).textContent).toContain('No proposals or remediation exceptions are currently queued')
  expect(tile(container).textContent).not.toContain('complete')
})

it('does not invent a queue count where assessment has no review data', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(AssessSummary, props)))
  expect(container.textContent).not.toContain('Review queue items')
  const source = readFileSync('src/Remediate.jsx', 'utf8')
  expect(source).toContain('reviewSummary={reviewCounts}')
  expect(source).toContain('reviewCount={reviewCounts.pendingItems}')
})
