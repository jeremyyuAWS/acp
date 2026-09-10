import { afterEach, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import Detail from './RemediationCountDetails.jsx'
import { listHitlQueue, getScanRemediationDiffs } from './api.js'
vi.mock('./api.js', () => ({ listHitlQueue: vi.fn(), getScanRemediationDiffs: vi.fn() }))
afterEach(async () => { await unmountAll(); vi.clearAllMocks() })
async function mount(kind, expected) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<Detail scanId="scan" kind={kind} expected={expected} onClose={() => {}} />))
  return container
}
it('groups five review tasks by SC without treating their finding counts as task counts', async () => {
  listHitlQueue.mockResolvedValue(Array.from({length:5}, (_,i) => ({id:i, file:i < 3 ? 'A.pdf' : 'B.pdf', rule_id:i < 3 ? 'SC_1_1_1' : 'SC_1_3_1', finding_count:2, status:'pending'})))
  const c = await mount('review',5)
  expect(listHitlQueue).toHaveBeenCalledWith('scan','pending')
  expect(c.textContent).toContain('5 of 5 review tasks loaded')
  expect(c.querySelectorAll('details')).toHaveLength(2)
  expect(c.querySelector('summary').textContent).toContain('SC 1.1.1 · 3 review tasks')
  expect(c.querySelector('details').open).toBe(false)
  await act(async () => c.querySelector('summary').click())
  expect(c.querySelector('details').open).toBe(true)
  expect(c.textContent).toContain('A.pdf')
})
it('shows four verification records and their before and after values', async () => {
  getScanRemediationDiffs.mockResolvedValue(Array.from({length:4},(_,i)=>({file:'A.pdf',rule_id:'SC_3_1_1',before:'Missing',after:'en',id:i})))
  const c = await mount('fixes',4)
  expect(c.textContent).toContain('4 of 4 verified change records loaded')
  expect(c.querySelectorAll('article')).toHaveLength(4)
  expect(c.textContent).toContain('BeforeMissingAfteren')
})
it('explicitly reports incomplete evidence instead of claiming the total is explained', async () => {
  getScanRemediationDiffs.mockResolvedValue([])
  const c = await mount('fixes',4)
  expect(c.querySelector('[role=alert]').textContent).toContain('cannot yet explain the full total')
})
