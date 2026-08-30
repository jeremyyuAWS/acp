/**
 * The shared /jobs feed: one request per equivalent query, correctly scoped, honestly timestamped.
 *
 * These test the FEED'S BEHAVIOUR, not the 38 component assertions that first surfaced it. The
 * failure mode this module could introduce is worse than the duplication it removes: a cache keyed
 * or cleared wrongly shows one account another's queue, or shows old data as current.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const getJobs = vi.fn()
const authEpoch = vi.fn(() => 0)
const apiBase = vi.fn(() => 'http://api.test')

vi.mock('./api.js', () => ({ getJobs: (...a) => getJobs(...a) }))
vi.mock('./apiIdentity.js', () => ({
  authEpoch: () => authEpoch(),
  apiBase: () => apiBase(),
}))

let subscribeJobs, resetJobsFeed, _feedState, STALE_AFTER_MS

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  getJobs.mockReset(); authEpoch.mockReset(); apiBase.mockReset()
  authEpoch.mockReturnValue(0); apiBase.mockReturnValue('http://api.test')
  getJobs.mockResolvedValue({ workers: 2, jobs: [{ id: 'j1' }] })
  ;({ subscribeJobs, resetJobsFeed, _feedState, STALE_AFTER_MS } = await import('./jobsFeed.js'))
})

afterEach(() => {
  // EXPLICIT cleanup, not a production behaviour bent to suit mocks: this module deliberately
  // keeps a cache across unmount, so a test that wants a cold start has to say so.
  resetJobsFeed()
  vi.useRealTimers()
})

const flush = async () => { await vi.advanceTimersByTimeAsync(0) }

describe('sharing one request', () => {
  it('serves many subscribers of the same query from ONE fetch', async () => {
    const a = vi.fn(); const b = vi.fn(); const c = vi.fn()
    subscribeJobs(null, a); subscribeJobs(null, b); subscribeJobs(null, c)
    await flush()

    expect(getJobs).toHaveBeenCalledTimes(1)
    expect(a).toHaveBeenCalled(); expect(b).toHaveBeenCalled(); expect(c).toHaveBeenCalled()
    expect(_feedState()).toHaveLength(1)
  })

  it('keeps DIFFERENT status filters as separate requests', async () => {
    // The queued list must never be inferred from the capped unfiltered list.
    subscribeJobs(null, vi.fn()); subscribeJobs('queued', vi.fn())
    await flush()
    expect(getJobs).toHaveBeenCalledTimes(2)
    expect(getJobs.mock.calls.map(([s]) => s).sort()).toEqual([null, 'queued'])
  })

  it('does not overlap polls when a response is slower than the interval', async () => {
    let resolve
    getJobs.mockImplementation(() => new Promise((r) => { resolve = r }))
    subscribeJobs(null, vi.fn(), { intervalMs: 1000 })
    await flush()
    expect(getJobs).toHaveBeenCalledTimes(1)

    // Several intervals pass with the first request still outstanding.
    await vi.advanceTimersByTimeAsync(5000)
    expect(getJobs).toHaveBeenCalledTimes(1)

    resolve({ workers: 1, jobs: [] })
    await flush()
    expect(getJobs).toHaveBeenCalledTimes(1)
  })

  it('polls at the SHORTEST interval any subscriber asked for', async () => {
    subscribeJobs(null, vi.fn(), { intervalMs: 10000 })
    subscribeJobs(null, vi.fn(), { intervalMs: 2000 })
    await flush()
    expect(getJobs).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2100)
    expect(getJobs).toHaveBeenCalledTimes(2)
  })
})

describe('freshness is reported, never faked', () => {
  it('hands a remounting subscriber the REAL fetch time, not the mount time', async () => {
    const first = vi.fn()
    const stop = subscribeJobs(null, first, { intervalMs: 60000 })
    await flush()
    const fetchedAt = first.mock.calls[0][1].fetchedAt
    stop()

    await vi.advanceTimersByTimeAsync(45000)   // well past STALE_AFTER_MS

    const second = vi.fn()
    subscribeJobs(null, second, { intervalMs: 60000 })
    const [, meta] = second.mock.calls[0]
    expect(meta.fetchedAt).toBe(fetchedAt)      // NOT refreshed by the act of mounting
    expect(meta.ageMs).toBeGreaterThanOrEqual(45000)
    expect(meta.stale).toBe(true)
  })

  it('labels a young cache as fresh', async () => {
    const a = vi.fn()
    const stop = subscribeJobs(null, a, { intervalMs: 60000 })
    await flush()
    stop()
    const b = vi.fn()
    subscribeJobs(null, b, { intervalMs: 60000 })
    expect(b.mock.calls[0][1].stale).toBe(false)
    expect(b.mock.calls[0][1].ageMs).toBeLessThan(STALE_AFTER_MS)
  })

  it('revalidates on remount when the cache is older than the subscriber accepts', async () => {
    const stop = subscribeJobs(null, vi.fn(), { intervalMs: 1000 })
    await flush()
    expect(getJobs).toHaveBeenCalledTimes(1)
    stop()
    await vi.advanceTimersByTimeAsync(5000)

    subscribeJobs(null, vi.fn(), { intervalMs: 1000 })
    await flush()
    expect(getJobs).toHaveBeenCalledTimes(2)     // served instantly AND refreshed
  })
})

describe('identity scoping', () => {
  it('never hands one account the previous account\'s payload', async () => {
    const first = vi.fn()
    const stop = subscribeJobs(null, first, { intervalMs: 60000 })
    await flush()
    expect(first.mock.calls[0][0].jobs).toEqual([{ id: 'j1' }])
    stop()

    authEpoch.mockReturnValue(1)                  // sign-out + sign-in as somebody else
    getJobs.mockResolvedValue({ workers: 9, jobs: [{ id: 'other' }] })

    const second = vi.fn()
    subscribeJobs(null, second, { intervalMs: 60000 })
    // Nothing may be delivered from cache here — the only call must be the fresh fetch.
    expect(second).not.toHaveBeenCalled()
    await flush()
    expect(second.mock.calls[0][0].jobs).toEqual([{ id: 'other' }])
  })

  it('drops the previous identity\'s cache rather than leaving it in memory', async () => {
    const stop = subscribeJobs(null, vi.fn(), { intervalMs: 60000 })
    await flush()
    stop()
    expect(_feedState().some((f) => f.hasCache)).toBe(true)

    authEpoch.mockReturnValue(1)
    subscribeJobs(null, vi.fn(), { intervalMs: 60000 })
    const keys = _feedState().map((f) => f.key)
    expect(keys.every((k) => k.includes('|1|'))).toBe(true)
    expect(keys.some((k) => k.includes('|0|'))).toBe(false)
  })

  it('keys by API endpoint as well as identity', async () => {
    subscribeJobs(null, vi.fn())
    await flush()
    apiBase.mockReturnValue('http://other.test')
    subscribeJobs(null, vi.fn())
    await flush()
    expect(_feedState()).toHaveLength(2)
  })
})

describe('teardown and late responses', () => {
  it('stops polling when the last subscriber leaves', async () => {
    const stop = subscribeJobs(null, vi.fn(), { intervalMs: 1000 })
    await flush()
    expect(getJobs).toHaveBeenCalledTimes(1)
    stop()
    await vi.advanceTimersByTimeAsync(10000)
    expect(getJobs).toHaveBeenCalledTimes(1)
  })

  it('keeps polling while OTHER subscribers remain', async () => {
    const stop = subscribeJobs(null, vi.fn(), { intervalMs: 1000 })
    subscribeJobs(null, vi.fn(), { intervalMs: 1000 })
    await flush()
    stop()
    await vi.advanceTimersByTimeAsync(1100)
    expect(getJobs).toHaveBeenCalledTimes(2)
  })

  it('discards a response that arrives after teardown', async () => {
    let resolve
    getJobs.mockImplementation(() => new Promise((r) => { resolve = r }))
    const late = vi.fn()
    const stop = subscribeJobs(null, late, { intervalMs: 1000 })
    await flush()
    stop()

    resolve({ workers: 99, jobs: [{ id: 'late' }] })
    await flush()

    expect(late).not.toHaveBeenCalled()
    // and it must not have repopulated the cache behind the teardown
    const cached = _feedState().find((f) => f.hasCache)
    expect(cached?.fetchedAt ?? null).toBeNull()
  })

  it('a response outstanding across a sign-out cannot land in the new session', async () => {
    let resolve
    getJobs.mockImplementation(() => new Promise((r) => { resolve = r }))
    subscribeJobs(null, vi.fn(), { intervalMs: 1000 })
    await flush()

    resetJobsFeed()                       // sign-out
    authEpoch.mockReturnValue(1)
    const next = vi.fn()
    getJobs.mockResolvedValue({ workers: 3, jobs: [{ id: 'mine' }] })
    subscribeJobs(null, next, { intervalMs: 1000 })
    await flush()

    resolve({ workers: 99, jobs: [{ id: 'PREVIOUS ACCOUNT' }] })   // the old request lands now
    await flush()

    const delivered = next.mock.calls.map(([d]) => d.jobs?.[0]?.id)
    expect(delivered).not.toContain('PREVIOUS ACCOUNT')
    expect(delivered).toContain('mine')
  })
})

describe('errors and recovery', () => {
  it('reports the error and keeps the last known payload with its age', async () => {
    const onData = vi.fn(); const onError = vi.fn()
    subscribeJobs(null, onData, { intervalMs: 1000, onError })
    await flush()
    expect(onData).toHaveBeenCalledTimes(1)

    getJobs.mockRejectedValue(new Error('unavailable'))
    await vi.advanceTimersByTimeAsync(1100)

    expect(onError).toHaveBeenCalled()
    const [err, meta] = onError.mock.calls[0]
    expect(err.message).toBe('unavailable')
    expect(meta.fetchedAt).not.toBeNull()      // last-known is still there, honestly aged
  })

  it('backs off after failures instead of hammering, then recovers', async () => {
    subscribeJobs(null, vi.fn(), { intervalMs: 1000, onError: vi.fn() })
    await flush()
    getJobs.mockRejectedValue(new Error('down'))

    await vi.advanceTimersByTimeAsync(1100)
    const afterFirstFailure = getJobs.mock.calls.length
    // The next attempt is backed off well beyond the plain interval.
    await vi.advanceTimersByTimeAsync(900)
    expect(getJobs.mock.calls.length).toBe(afterFirstFailure)

    getJobs.mockResolvedValue({ workers: 1, jobs: [] })
    await vi.advanceTimersByTimeAsync(60000)
    expect(getJobs.mock.calls.length).toBeGreaterThan(afterFirstFailure)
  })
})
