import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import useRemediationAttemptStory from './useRemediationAttemptStory.js'
import { getRunInsights } from './remediationRunInsightsClient.js'
import { authEpoch } from './apiIdentity.js'
vi.mock('./remediationRunInsightsClient.js', () => ({ getRunInsights: vi.fn() }))
vi.mock('./apiIdentity.js', () => ({ authEpoch: vi.fn(() => 1) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const data = { scan_id: 'scan', batch_id: 'batch', attempts: [{ attempt_id: 'saved' }] }
let current
function Harness(props) { current = useRemediationAttemptStory(props); return createElement('div', null, current.data?.attempts?.[0]?.attempt_id || '') }
async function mount(extra = {}) {
  const { root, container } = createTestRoot()
  const props = { scanId: 'scan', batchId: 'batch', open: true, live: true, ...extra }
  const render = overrides => act(async () => root.render(createElement(Harness, { ...props, ...overrides })))
  await render()
  return { root, container, render }
}
beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); authEpoch.mockReturnValue(1); getRunInsights.mockResolvedValue(data) })
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.restoreAllMocks() })
it('polls one saved page while live, retaining last good data when refresh fails', async () => {
  const { container } = await mount()
  getRunInsights.mockRejectedValue(new Error('offline'))
  await act(async () => vi.advanceTimersByTime(15_000))
  expect(getRunInsights).toHaveBeenCalledTimes(2)
  expect(current.error).toBe(true)
  expect(container.textContent).toBe('saved')
})
it.each([{ open: false }, { live: false }, { paused: true }])('stops repeat reads when %j', async options => {
  await mount(options)
  const initial = getRunInsights.mock.calls.length
  await act(async () => vi.advanceTimersByTime(60_000))
  expect(getRunInsights).toHaveBeenCalledTimes(initial)
})
it('aborts and rejects a late response after switching run or page', async () => {
  let resolve
  getRunInsights.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const { render, container } = await mount()
  const signal = getRunInsights.mock.calls[0][2]
  getRunInsights.mockResolvedValue({ ...data, batch_id: 'other', attempts: [{ attempt_id: 'new' }] })
  await render({ batchId: 'other', offset: 100 })
  expect(signal.aborted).toBe(true)
  await act(async () => resolve(data))
  expect(container.textContent).toBe('new')
})
it('does not render an old account response or mismatched batch', async () => {
  let resolve
  getRunInsights.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const { render, container } = await mount()
  authEpoch.mockReturnValue(2)
  await act(async () => resolve(data))
  expect(container.textContent).toBe('')
  getRunInsights.mockResolvedValue({ ...data, batch_id: 'wrong' })
  await render()
  expect(current.error).toBe(true)
  expect(container.textContent).toBe('')
})
it('pauses polling when hidden, resumes on visibility, and aborts on collapse', async () => {
  const { render } = await mount()
  const visibility = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  await act(async () => vi.advanceTimersByTime(60_000))
  expect(getRunInsights).toHaveBeenCalledTimes(1)
  visibility.mockReturnValue(false)
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  expect(getRunInsights).toHaveBeenCalledTimes(2)
  const signal = getRunInsights.mock.calls[1][2]
  await render({ open: false })
  expect(signal.aborted).toBe(true)
})
