import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Mock only what the hook imports from api.
const getScanLive = vi.fn()
vi.mock('./api', () => ({ getScanLive: (...a) => getScanLive(...a) }))

import { useLiveSnapshot } from './useLiveSnapshot.js'

// A probe component that surfaces the hook's current snapshot as text so we can assert on it.
function Probe({ scanId, active = true }) {
  const s = useLiveSnapshot(scanId, { active, intervalMs: 1000 })
  return createElement('div', null, s ? `seq:${s.sequence} done:${s.kpis?.completed}` : 'none')
}

const frame = (sequence, completed) => ({ available: true, sequence, kpis: { completed } })

async function flush() { await act(async () => { await Promise.resolve(); await Promise.resolve() }) }

beforeEach(() => { getScanLive.mockReset(); vi.useFakeTimers() })
afterEach(async () => { vi.useRealTimers(); await unmountAll() })

describe('useLiveSnapshot', () => {
  it('polls and shows the first frame', async () => {
    getScanLive.mockResolvedValue(frame(1, 10))
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(Probe, { scanId: 's1' })) })
    await flush()
    expect(container.textContent).toBe('seq:1 done:10')
    expect(getScanLive).toHaveBeenCalledWith('s1')
  })

  it('ignores an out-of-order (lower-sequence) frame — reconnect safety', async () => {
    getScanLive.mockResolvedValueOnce(frame(5, 50)).mockResolvedValueOnce(frame(3, 30))
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(Probe, { scanId: 's1' })) })
    await flush()                                   // frame seq 5
    expect(container.textContent).toBe('seq:5 done:50')
    await act(async () => { vi.advanceTimersByTime(1000) }); await flush()   // frame seq 3 arrives
    expect(container.textContent).toBe('seq:5 done:50')                       // stale frame ignored
  })

  it('keeps the last good snapshot when a poll errors (fail-soft)', async () => {
    getScanLive.mockResolvedValueOnce(frame(1, 10)).mockRejectedValueOnce(new Error('blip'))
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(Probe, { scanId: 's1' })) })
    await flush()
    expect(container.textContent).toBe('seq:1 done:10')
    await act(async () => { vi.advanceTimersByTime(1000) }); await flush()   // errors
    expect(container.textContent).toBe('seq:1 done:10')                       // last good retained
  })

  it('re-polls immediately when the tab becomes visible again (refocus-fresh)', async () => {
    getScanLive.mockResolvedValue(frame(1, 10))
    const { root } = createTestRoot()
    await act(async () => { root.render(createElement(Probe, { scanId: 's1' })) })
    await flush()
    const before = getScanLive.mock.calls.length
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
    await flush()
    expect(getScanLive.mock.calls.length).toBeGreaterThan(before)   // an extra poll, not just the interval
  })

  it('does not poll without a scanId or when inactive', async () => {
    const { root } = createTestRoot()
    await act(async () => { root.render(createElement(Probe, { scanId: null })) })
    await act(async () => { root.render(createElement(Probe, { scanId: 's1', active: false })) })
    await flush()
    expect(getScanLive).not.toHaveBeenCalled()
  })

  it('clears the completed assessment frame when its stage becomes inactive', async () => {
    getScanLive.mockResolvedValue(frame(37, 37))
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(Probe, { scanId: 's1', active: true })) })
    await flush()
    expect(container.textContent).toBe('seq:37 done:37')

    await act(async () => { root.render(createElement(Probe, { scanId: 's1', active: false })) })
    await flush()
    expect(container.textContent).toBe('none')
  })

  it('does not carry a completed frame into a different scan', async () => {
    getScanLive.mockResolvedValueOnce(frame(37, 37)).mockImplementation(() => new Promise(() => {}))
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(Probe, { scanId: 's1' })) })
    await flush()
    expect(container.textContent).toBe('seq:37 done:37')

    await act(async () => { root.render(createElement(Probe, { scanId: 's2' })) })
    await flush()
    expect(container.textContent).toBe('none')
  })
})
