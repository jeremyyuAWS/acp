import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import useWaterfallActivity from './useWaterfallActivity.js'
import { getWaterfall } from './remediationWaterfallClient.js'
vi.mock('./remediationWaterfallClient.js', () => ({ getWaterfall: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
function Harness({ scan = 'a', batch = 'one', paused = false }) {
  return <output>{JSON.stringify(useWaterfallActivity(scan, batch, paused))}</output>
}
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.clearAllMocks() })
it('keeps the last good snapshot on errors and stops network refresh while paused', async () => {
  vi.useFakeTimers()
  getWaterfall.mockResolvedValueOnce({ revision: 'one', generated_at: 'then' }).mockRejectedValue(new Error('offline'))
  const { root, container } = createTestRoot()
  await act(async () => root.render(<Harness />))
  expect(container.textContent).toContain('"revision":"one"')
  await act(async () => vi.advanceTimersByTimeAsync(5000))
  expect(container.textContent).toContain('"error":true')
  expect(container.textContent).toContain('"generated_at":"then"')
  await act(async () => root.render(<Harness paused />))
  const calls = getWaterfall.mock.calls.length
  await act(async () => vi.advanceTimersByTimeAsync(15000))
  expect(getWaterfall).toHaveBeenCalledTimes(calls)
})
it('never lets a delayed old-run response replace the selected run', async () => {
  let resolveOld
  getWaterfall.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValueOnce({ revision: 'new-run' })
  const { root, container } = createTestRoot()
  await act(async () => root.render(<Harness />))
  await act(async () => root.render(<Harness batch="two" />))
  await act(async () => resolveOld({ revision: 'old-run' }))
  expect(container.textContent).toContain('new-run')
  expect(container.textContent).not.toContain('old-run')
})
