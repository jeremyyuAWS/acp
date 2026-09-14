import React from 'react'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
const history = vi.fn(), stream = vi.fn(() => ({ close: vi.fn() }))
vi.mock('./api.js', () => ({ getRecentRemediationActivity: (...a) => history(...a), getRemediationSnapshot: vi.fn(async () => ({ terminal: false, revision: 1 })), openRemediationStream: (...a) => stream(...a) }))
const { useRemediationRun } = await import('./useRemediationRun.js')
let current, host, root
function Harness({ id = 'run' }) { current = useRemediationRun(id); return null }
const event = seq => ({ seq, kind: 'remediate.verified', document: `${seq}.pdf`, detail: { fixes: 1 } })
beforeEach(() => { vi.useFakeTimers(); history.mockReset(); stream.mockClear(); host = document.createElement('div'); root = createRoot(host) })
afterEach(async () => { await act(async () => root.unmount()); vi.useRealTimers() })
it('loads every page and prepends live events without losing older history', async () => {
  history.mockResolvedValueOnce({ available: true, events: Array.from({ length: 2000 }, (_, i) => event(i + 1)), latest_seq: 2000 })
    .mockResolvedValueOnce({ available: true, events: [event(2001)], latest_seq: 2001 })
  await act(async () => root.render(<Harness />))
  expect(history.mock.calls.map(c => c[1].afterSeq)).toEqual([0, 2000])
  expect(current.events).toHaveLength(2001)
  await act(async () => stream.mock.calls[0][1].onEvent(event(2002), '2002'))
  expect(current.events).toHaveLength(2002)
  expect(current.events[0].id).toBe('2002')
  expect(current.events.at(-1).id).toBe('1')
})
it('polls incrementally, deduplicates overlaps and retains history on transient errors', async () => {
  history.mockResolvedValueOnce({ available: true, events: [event(1), event(2)], latest_seq: 2 })
    .mockRejectedValueOnce(new Error('temporary'))
    .mockResolvedValueOnce({ available: true, events: [event(2), event(3)], latest_seq: 3 })
  await act(async () => root.render(<Harness />))
  await act(async () => stream.mock.calls[0][1].onError())
  expect(current.events.map(e => e.id)).toEqual(['2', '1'])
  await act(async () => vi.advanceTimersByTimeAsync(5000))
  expect(history.mock.calls[2][1].afterSeq).toBe(2)
  expect(current.events.map(e => e.id)).toEqual(['3', '2', '1'])
})
it('clears inaccessible history and does not keep polling it', async () => {
  history.mockResolvedValueOnce({ available: true, events: [event(1)], latest_seq: 1 })
    .mockResolvedValueOnce({ available: false, reason: 'scan_not_found' })
  await act(async () => root.render(<Harness />))
  await act(async () => stream.mock.calls[0][1].onError())
  expect(current.events).toEqual([])
  await act(async () => vi.advanceTimersByTimeAsync(10000))
  expect(history).toHaveBeenCalledTimes(2)
})
it('starts a new cursor and removes the prior run narrative on run change', async () => {
  history.mockResolvedValueOnce({ available: true, events: [event(10)], latest_seq: 10 })
    .mockResolvedValueOnce({ available: true, events: [event(1)], latest_seq: 1 })
  await act(async () => root.render(<Harness />))
  await act(async () => root.render(<Harness id="next" />))
  expect(history.mock.calls[1]).toEqual(['next', { afterSeq: 0, limit: 2000 }])
  expect(current.events.map(e => e.id)).toEqual(['1'])
})
