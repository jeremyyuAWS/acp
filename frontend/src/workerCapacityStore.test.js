import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const getWorkerCapacity = vi.fn()
vi.mock('./api.js', () => ({ getWorkerCapacity: (...a) => getWorkerCapacity(...a) }))

const { subscribeWorkerCapacity, _resetForTests } = await import('./workerCapacityStore.js')

beforeEach(() => {
  vi.useFakeTimers()
  getWorkerCapacity.mockReset()
  _resetForTests()
})
afterEach(() => { vi.useRealTimers() })

const flush = async () => { await Promise.resolve(); await Promise.resolve() }

describe('workerCapacityStore', () => {
  it('fetches once immediately on the first subscriber', async () => {
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 2 })
    const fn = vi.fn()
    subscribeWorkerCapacity(fn)
    await flush()
    expect(getWorkerCapacity).toHaveBeenCalledTimes(1)
    expect(fn).toHaveBeenCalledWith({ configured: true, current_replicas: 2 })
  })

  it('does not fetch again for a second concurrent subscriber — one poller, not two', async () => {
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 2 })
    const a = vi.fn(); const b = vi.fn()
    subscribeWorkerCapacity(a)
    await flush()
    subscribeWorkerCapacity(b)
    await flush()
    // Only the first subscriber's mount triggers a fetch; the second reuses the cached value.
    expect(getWorkerCapacity).toHaveBeenCalledTimes(1)
    expect(b).toHaveBeenCalledWith({ configured: true, current_replicas: 2 })
  })

  it('hands a newly-subscribing listener the cached value immediately, synchronously', async () => {
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 5 })
    subscribeWorkerCapacity(vi.fn())
    await flush()
    const late = vi.fn()
    subscribeWorkerCapacity(late)
    expect(late).toHaveBeenCalledWith({ configured: true, current_replicas: 5 })
  })

  it('polls again after 30s while at least one subscriber remains', async () => {
    getWorkerCapacity.mockResolvedValue({ configured: true, current_replicas: 1 })
    subscribeWorkerCapacity(vi.fn())
    await flush()
    expect(getWorkerCapacity).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(30000)
    await flush()
    expect(getWorkerCapacity).toHaveBeenCalledTimes(2)
  })

  it('stops polling once the last subscriber unsubscribes', async () => {
    getWorkerCapacity.mockResolvedValue({ configured: true })
    const unsub = subscribeWorkerCapacity(vi.fn())
    await flush()
    unsub()
    vi.advanceTimersByTime(60000)
    await flush()
    expect(getWorkerCapacity).toHaveBeenCalledTimes(1)   // no further polls once unsubscribed
  })

  it('resumes polling (with a fresh fetch) when a new subscriber arrives after the last one left', async () => {
    getWorkerCapacity.mockResolvedValue({ configured: true })
    const unsub = subscribeWorkerCapacity(vi.fn())
    await flush()
    unsub()
    subscribeWorkerCapacity(vi.fn())
    await flush()
    expect(getWorkerCapacity).toHaveBeenCalledTimes(2)
  })

  it('a failed poll leaves the cached value alone rather than clearing it', async () => {
    getWorkerCapacity.mockResolvedValueOnce({ configured: true, current_replicas: 3 })
    const a = vi.fn()
    subscribeWorkerCapacity(a)
    await flush()
    getWorkerCapacity.mockRejectedValueOnce(new Error('network error'))
    vi.advanceTimersByTime(30000)
    await flush()
    // The failing poll must not have crashed or unsubscribed anyone; a late subscriber still
    // gets the last GOOD value, not undefined.
    const late = vi.fn()
    subscribeWorkerCapacity(late)
    expect(late).toHaveBeenCalledWith({ configured: true, current_replicas: 3 })
  })

  it('does not overlap two fetches if a poll is still in flight when the interval fires again', async () => {
    let resolve
    getWorkerCapacity.mockReturnValueOnce(new Promise((r) => { resolve = r }))
    subscribeWorkerCapacity(vi.fn())
    await flush()
    expect(getWorkerCapacity).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(30000)   // interval fires while the first fetch is still pending
    await flush()
    expect(getWorkerCapacity).toHaveBeenCalledTimes(1)   // still just the one in-flight call
    resolve({ configured: true })
    await flush()
  })

  it('stops delivering to an unsubscribed listener', async () => {
    getWorkerCapacity.mockResolvedValue({ configured: true })
    const fn = vi.fn()
    const unsub = subscribeWorkerCapacity(fn)
    await flush()
    unsub()
    fn.mockClear()
    subscribeWorkerCapacity(vi.fn())
    await flush()
    expect(fn).not.toHaveBeenCalled()
  })
})
