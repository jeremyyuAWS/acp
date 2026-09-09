import { act, createElement } from 'react'
import { afterEach, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { createTestRoot, unmountAll } from './testRoots.js'
import { reviewableRemediationItems } from './remediationReviewAvailability.js'
import { remediationReviewCounts } from './remediationCountSummary.js'
import { laneOf, LANES } from './remediationInboxModel.js'
import RemediationInbox from './RemediationInbox.jsx'

afterEach(unmountAll)
const findings = Array.from({ length: 80 }, (_, id) => ({ id: `q${id}`, file: `document-${id % 39}.docx`,
  rule_id: '1.1.1', title: 'Non-text Content', aiDraftable: true, hasProposal: false, after: null }))

it('does not offer the screenshot’s 80 assessment placeholders as AI suggestions', () => {
  const rows = reviewableRemediationItems(findings)
  expect(rows).toHaveLength(0)
  expect(remediationReviewCounts(rows).pendingItems).toBe(0)
  expect(laneOf(findings[0])).toBe(LANES.manual)
  const source = readFileSync('src/Remediate.jsx', 'utf8')
  expect(source).not.toContain('autoPopulateHitlQueue(')
  expect(source).toContain('const inboxQueue = reviewableRemediationItems(')
  expect(source).toContain('No fixes to review yet.')
})

it('shows a generated proposal during processing, then undrafted exceptions after completion', async () => {
  const generated = { ...findings[0], hasProposal: true, after: 'A chart showing quarterly sales.' }
  const queued = [generated, ...findings.slice(1)]
  const { root, container } = createTestRoot()
  const render = async exceptions => act(async () => root.render(createElement(RemediationInbox, {
    queue: reviewableRemediationItems(queued, { exceptions }), decisions: {}, scanId: 'test',
  })))
  await render(null)
  expect(container.querySelectorAll('.rinbox-row')).toHaveLength(1)
  expect(container.textContent).toContain('A chart showing quarterly sales.')
  await render({ groups: [{ items: findings.map(row => ({ file: row.file, outcome: 'review' })) }] })
  const manualTab = [...container.querySelectorAll('[role=tab]')].find(el => el.textContent.startsWith('Fix manually'))
  expect(manualTab.textContent).toContain('79')
  await act(async () => manualTab.click())
  expect(container.textContent).not.toContain('AI-drafted fix')
})

it('preserves actual prior proposals, applied fixes, decisions and blocked work before another plan runs', () => {
  const retained = [
    { ...findings[0], after: 'Actual stored draft' },
    { ...findings[1], autoApplied: true },
    { ...findings[2], status: 'approved' },
    { ...findings[3], status: 'blocked' },
  ]
  expect(reviewableRemediationItems([...findings, ...retained])).toEqual(retained)
  expect(reviewableRemediationItems(findings, { exceptions: { groups: [] } })).toEqual([])
})

it('shows undrafted issues for a document that has finished remediation while others still run', () => {
  const files = [{ file: findings[0].file, remediated_at: '2026-09-09T12:00:00Z' }]
  const rows = reviewableRemediationItems(findings, { files })
  expect(rows.length).toBeGreaterThan(0)
  expect(rows.every(row => row.file === files[0].file)).toBe(true)
})

it('does not promote outside-batch or still-processing findings when a subset finishes', () => {
  const exceptions = { groups: [{ items: [
    { file: findings[0].file, outcome: 'review' },
    { file: findings[1].file, outcome: null },
    { file: findings[2].file, outcome: 'processing' },
    { file: findings[3].file, outcome: 'failed' },
  ] }] }
  const rows = reviewableRemediationItems(findings.slice(0, 4), { exceptions })
  expect(rows.map(row => row.id)).toEqual(['q0', 'q3'])
  expect(reviewableRemediationItems([{ ...findings[1], rejectedFix: true }])).toHaveLength(1)
})
