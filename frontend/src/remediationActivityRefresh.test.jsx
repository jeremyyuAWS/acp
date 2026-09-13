import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { Activity } from './RemediationOpsPanel.jsx'
afterEach(unmountAll)
const event = (key, tone = 'success') => ({ key, documentKey: 'doc:a', tone, line: `Update ${key}`, kind: tone === 'attention' ? 'scan.retrying' : 'remediate.verified' })
it('keeps expanded document history open as the lead changes and animates only new events', async () => {
  const { root, container } = createTestRoot()
  const rows = [event('2'), event('1')]
  await act(async () => root.render(<Activity events={rows} />))
  expect(container.querySelector('.remops-activity-fresh')).toBeNull()
  const details = container.querySelector('details'); details.open = true
  await act(async () => root.render(<Activity events={[event('3', 'attention'), ...rows]} />))
  expect(container.querySelector('details')).toBe(details)
  expect(details.open).toBe(true)
  expect(container.querySelector('.remops-activity-retry.remops-activity-fresh')).not.toBeNull()
})
it('does not animate the first saved history loaded after an empty initial render', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<Activity events={[]} status="loading" />))
  await act(async () => root.render(<Activity events={[event('1')]} />))
  expect(container.querySelector('.remops-activity-fresh')).toBeNull()
})
it('resets activity history and motion when the run scope changes', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<Activity key="run:1" events={[event('2'), event('1')]} />))
  container.querySelector('details').open = true
  await act(async () => root.render(<Activity key="run:2" events={[event('4'), event('3')]} />))
  expect(container.querySelector('details').open).toBe(false)
  expect(container.querySelector('.remops-activity-fresh')).toBeNull()
})
