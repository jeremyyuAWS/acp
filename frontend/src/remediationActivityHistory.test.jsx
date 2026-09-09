import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
const api = vi.hoisted(() => ({ getRemediationSnapshot: vi.fn(), getRecentRemediationActivity: vi.fn(), openRemediationStream: vi.fn() }))
vi.mock('./api.js', () => api)
import { useRemediationRun } from './useRemediationRun.js'
let current
const event = seq => ({ seq, kind: 'remediate.document_completed', document: `file-${seq}.pdf`, occurred_at: '2026-09-09T12:00:00Z' })
function Harness({ run = 'run' }) { current = useRemediationRun(run); return null }
async function mount() {
  api.getRemediationSnapshot.mockResolvedValue({ revision: 1, terminal: true })
  api.openRemediationStream.mockReturnValue({ close: vi.fn() })
  const { root } = createTestRoot()
  await act(async () => root.render(<Harness />))
  return root
}
afterEach(async () => { await unmountAll(); vi.resetAllMocks(); vi.useRealTimers() })
it('restores saved activity on a finished run without a live event', async () => {
  api.getRecentRemediationActivity.mockResolvedValue({ available: true, events: [event(1), event(2)] })
  await mount()
  expect(current.events.map(e => e.id)).toEqual(['2', '1'])
  expect(current.activityStatus).toBe('ready')
})
it('merges delayed history behind newer live events, deduplicates, and ignores prior-run responses', async () => {
  let resolve
  api.getRecentRemediationActivity.mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const root = await mount()
  await act(async () => api.openRemediationStream.mock.calls[0][1].onEvent(event(3), 3))
  await act(async () => resolve({ available: true, events: [event(1), event(3)] }))
  expect(current.events.map(e => e.id)).toEqual(['3', '1'])
  let old
  api.getRecentRemediationActivity.mockImplementationOnce(() => new Promise(r => { old = r }))
  await act(async () => api.openRemediationStream.mock.calls[0][1].onDone())
  api.getRecentRemediationActivity.mockResolvedValue({ available: true, events: [event(8)] })
  await act(async () => root.render(<Harness run="other" />))
  await act(async () => old({ available: true, events: [event(99)] }))
  expect(current.events.map(e => e.id)).toEqual(['8'])
})
it('keeps unknown distinct from empty and fetches activity during polling fallback', async () => {
  vi.useFakeTimers()
  api.getRecentRemediationActivity.mockRejectedValue(new Error('offline'))
  await mount()
  expect(current.activityStatus).toBe('unavailable')
  expect(current.events).toEqual([])
  const handlers = api.openRemediationStream.mock.calls[0][1]
  api.getRecentRemediationActivity.mockResolvedValue({ available: true, events: [event(4)] })
  await act(async () => handlers.onError())
  expect(current.events[0].id).toBe('4')
  expect(current.activityStatus).toBe('ready')
})
