import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import RealtimeShadowPanel from './RealtimeShadowPanel.jsx'
import { RealtimeShadowClient } from './realtimeShadowClient.js'

const envelope = (id, sequence, overrides = {}) => ({
  event_id: id, event_version: 1, event_type: 'scan.lifecycle.completed',
  occurred_at: new Date().toISOString(), tenant_id: 'tenant-1', correlation_id: 'scan-1',
  source: 'discovery', priority: 'high', sequence, payload: {}, ...overrides,
})

function panelClient(initial = {}) {
  let health = { state: 'idle', latencyMs: null, reconnects: 0, ...initial }
  const healthListeners = new Set(); const eventListeners = new Set()
  return {
    start: vi.fn(), stop: vi.fn(), snapshot: () => health,
    subscribe(fn) { healthListeners.add(fn); fn(health); return () => healthListeners.delete(fn) },
    onEvent(fn) { eventListeners.add(fn); return () => eventListeners.delete(fn) },
    health(next) { health = { ...health, ...next }; healthListeners.forEach((fn) => fn(health)) },
    event(next) { eventListeners.forEach((fn) => fn(next)) },
  }
}

beforeEach(() => vi.useFakeTimers())
afterEach(async () => { vi.useRealTimers(); await unmountAll() })

describe('realtime shadow transport', () => {
  it('deduplicates and rejects out-of-order events while preserving lifecycle transitions', () => {
    const client = new RealtimeShadowClient()
    const received = []
    client.onEvent((event) => received.push(event.event_id))
    expect(client.accept(envelope('event-2', 2))).toBe(true)
    expect(client.accept(envelope('event-2', 2))).toBe(false)
    expect(client.accept(envelope('event-1', 1))).toBe(false)
    expect(client.accept(envelope('event-3', 3))).toBe(true)
    expect(received).toEqual(['event-2', 'event-3'])
  })

  it('coalesces only low-priority progress, retaining the newest ordered update', () => {
    const client = new RealtimeShadowClient({ coalesceMs: 50 })
    const received = []
    client.onEvent((event) => received.push(event.event_id))
    client.accept(envelope('p1', 1, { priority: 'low', event_type: 'scan.progress' }))
    client.accept(envelope('p2', 2, { priority: 'low', event_type: 'scan.progress' }))
    expect(received).toEqual([])
    vi.advanceTimersByTime(50)
    expect(received).toEqual(['p2'])
  })

  it('reconnects with Last-Event-ID after a transport failure', async () => {
    const fetchImpl = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockImplementationOnce(() => new Promise(() => {}))
    const client = new RealtimeShadowClient({ fetchImpl, retryMs: 25 })
    client.accept(envelope('resume-from-me', 1))
    client.start()
    await act(async () => { await Promise.resolve() })
    expect(client.snapshot().state).toBe('fallback')
    await act(async () => { vi.advanceTimersByTime(25); await Promise.resolve() })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(fetchImpl.mock.calls[1][1].headers['Last-Event-ID']).toBe('resume-from-me')
    client.stop()
  })

  it('aborts and cancels retry work during cleanup', async () => {
    let signal
    const fetchImpl = vi.fn((_url, options) => { signal = options.signal; return new Promise(() => {}) })
    const client = new RealtimeShadowClient({ fetchImpl })
    client.start()
    await Promise.resolve()
    client.stop()
    expect(signal.aborted).toBe(true)
    expect(client.snapshot().state).toBe('idle')
  })
})

describe('RealtimeShadowPanel', () => {
  it('is DOM-equivalent when the default-off flag is disabled', async () => {
    const client = panelClient()
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement('main', null, 'production UI', createElement(RealtimeShadowPanel, { enabled: false, client }))) })
    expect(container.innerHTML).toBe('<main>production UI</main>')
    expect(client.start).not.toHaveBeenCalled()
  })

  it('shows health and fallback without replacing visible operational values', async () => {
    const client = panelClient()
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement('main', null,
      createElement('output', { 'data-testid': 'production-value' }, '42 complete'),
      createElement(RealtimeShadowPanel, { enabled: true, client, currentSnapshot: { completed: 42 } }),
    )) })
    await act(async () => {
      client.event(envelope('snapshot', 1, { payload: { snapshot: { completed: 41 } } }))
      client.health({ state: 'fallback' })
    })
    expect(container.querySelector('[data-testid="production-value"]').textContent).toBe('42 complete')
    expect(container.textContent).toContain('UI differences1')
    expect(container.textContent).toContain('Existing live updates remain active.')
    expect(client.start).toHaveBeenCalledTimes(1)
  })

  it('unsubscribes and stops the shared connection on unmount', async () => {
    const client = panelClient()
    const { root } = createTestRoot()
    await act(async () => { root.render(createElement(RealtimeShadowPanel, { enabled: true, client })) })
    await act(async () => { root.render(null) })
    expect(client.stop).toHaveBeenCalledTimes(1)
  })
})
