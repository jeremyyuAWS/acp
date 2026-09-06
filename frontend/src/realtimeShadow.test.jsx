import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import RealtimeShadowPanel from './RealtimeShadowPanel.jsx'
import { RealtimeShadowClient } from './realtimeShadowClient.js'

const envelope = (sequence, overrides = {}) => ({
  event_id: `00000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`,
  stream_id: `${sequence}-0`, schema_version: '1.0', kind: 'discover.completed',
  occurred_at: new Date().toISOString(), observed_at: new Date().toISOString(),
  owner_scope: '0123456789abcdef01234567', priority: 1, source_seq: sequence,
  scan_id: 'scan-1', payload: {}, ...overrides,
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
    const second = envelope(2); const first = envelope(1); const third = envelope(3)
    expect(client.accept(second, '2-0')).toBe(true)
    expect(client.accept(second, '2-0')).toBe(false)
    expect(client.accept(first, '1-0')).toBe(false)
    expect(client.accept(third, '3-0')).toBe(true)
    expect(received).toEqual([second.event_id, third.event_id])
    expect(client.snapshot().lastEventId).toBe('3-0')
  })

  it('coalesces only low-priority progress, retaining the newest ordered update', () => {
    const client = new RealtimeShadowClient({ coalesceMs: 50 })
    const received = []
    client.onEvent((event) => received.push(event.event_id))
    client.accept(envelope(1, { priority: 3, kind: 'assess.progressed', coalesce_key: 'scan-1' }))
    client.accept(envelope(2, { priority: 3, kind: 'assess.progressed', coalesce_key: 'scan-1' }))
    expect(received).toEqual([])
    vi.advanceTimersByTime(50)
    expect(received).toEqual([envelope(2).event_id])
  })

  it('reconnects with Last-Event-ID after a transport failure', async () => {
    const fetchImpl = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockImplementationOnce(() => new Promise(() => {}))
    const client = new RealtimeShadowClient({ endpoint: '/api/realtime/v1/stream', headersProvider: () => ({ Authorization: 'Bearer browser-token' }), fetchImpl, retryMs: 25 })
    client.accept(envelope(7, { stream_id: '1700000000000-7' }), '1700000000000-7')
    client.start()
    await act(async () => { await Promise.resolve() })
    expect(client.snapshot().state).toBe('fallback')
    await act(async () => { vi.advanceTimersByTime(25); await Promise.resolve() })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(fetchImpl.mock.calls[1][1].headers['Last-Event-ID']).toBe('1700000000000-7')
    expect(fetchImpl.mock.calls[1][1].headers.Authorization).toBe('Bearer browser-token')
    client.stop()
  })

  it('reconciles an unusable cursor from the authoritative snapshot and clears it', async () => {
    const snapshotProvider = vi.fn().mockResolvedValue({ scan_id: 'scan-1', scan_status: 'running' })
    const client = new RealtimeShadowClient({ snapshotProvider })
    const received = []
    client.onEvent((event) => received.push(event))
    client.accept(envelope(9), '9-0')
    await client.reconcile('stale')
    expect(snapshotProvider).toHaveBeenCalledTimes(1)
    expect(received.at(-1)).toMatchObject({ kind: 'snapshot', control: true, payload: { snapshot: { scan_id: 'scan-1' } } })
    expect(client.snapshot()).toMatchObject({ state: 'connected', lastEventId: null, error: null })
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
      client.event(envelope(1, { payload: { snapshot: { completed: 41 } } }))
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
