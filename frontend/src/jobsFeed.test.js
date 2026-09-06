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
  // The backoff tests pin Math.random with vi.spyOn. Leaving it pinned would silently fix the
  // jitter for every later test in the file — the same class of defect as the flake it replaced,
  // just pointing the other way. Only spies are restored; the vi.fn() module mocks are reset in
  // beforeEach and are unaffected.
  vi.restoreAllMocks()
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

  /**
   * THE JITTER IS PINNED, because otherwise this asserts the dice.
   *
   * `delayFor` is `min(interval * 2**failures, MAX_BACKOFF) * (0.5 + Math.random() * 0.5)`. With
   * `intervalMs: 1000` and one failure that is 2000 * [0.5, 1) — a range of [1000, 2000). The
   * earlier version of this test advanced to exactly 2000ms and asserted no retry had fired,
   * which is the range's BOTTOM EDGE: whenever Math.random() came up near zero the retry landed
   * on 2000 and the test failed with `expected 3 to be 2`. It did so on unrelated PRs, costing a
   * CI cycle each time (#1579 was one).
   *
   * So the fix is not to widen the window — that would leave a smaller flake — but to remove the
   * randomness from the assertion and then assert what the implementation actually guarantees.
   *
   * WHAT IT ACTUALLY GUARANTEES, measured by stepping the fake clock 1ms at a time and recording
   * every call instant:
   *
   *   jitter 0 (floor)   calls at 1000, 2000, 4000, 8000   gaps 1000, 2000, 4000
   *   jitter ~1 (top)    calls at 1000, 2999, 6998         gaps 1999, 3999
   *
   * Two properties hold at BOTH extremes, and they are the honest statement of "does not hammer":
   * a retry never comes sooner than the plain interval, and the wait grows with each consecutive
   * failure. What does NOT hold is the old comment's claim that the first retry is "well beyond
   * the plain interval" — at the jitter floor it is exactly the plain interval. The old assertion
   * was stronger than the code, which is why it failed at random rather than consistently.
   */
  const retryInstants = async (jitter, { intervalMs, window }) => {
    vi.spyOn(Math, 'random').mockReturnValue(jitter)
    subscribeJobs(null, vi.fn(), { intervalMs, onError: vi.fn() })
    await flush()
    getJobs.mockRejectedValue(new Error('down'))
    const at = []
    let seen = getJobs.mock.calls.length
    for (let t = 1; t <= window; t += 1) {
      await vi.advanceTimersByTimeAsync(1)
      if (getJobs.mock.calls.length > seen) { seen = getJobs.mock.calls.length; at.push(t) }
    }
    return at
  }

  // Both ends of the jitter range, because a property that holds only at one end is the bug this
  // file just had. 0 is the floor that used to break it; 0.999999 stands in for the open top.
  for (const [label, jitter] of [['the jitter floor', 0], ['the jitter ceiling', 0.999999]]) {
    it(`never retries sooner than the plain interval, at ${label}`, async () => {
      const at = await retryInstants(jitter, { intervalMs: 1000, window: 8000 })
      expect(at.length).toBeGreaterThan(1)          // a first poll plus at least one retry
      const gaps = at.slice(1).map((t, i) => t - at[i])
      for (const gap of gaps) expect(gap).toBeGreaterThanOrEqual(1000)
    })

    it(`waits longer after each consecutive failure, at ${label}`, async () => {
      const at = await retryInstants(jitter, { intervalMs: 1000, window: 8000 })
      const gaps = at.slice(1).map((t, i) => t - at[i])
      expect(gaps.length).toBeGreaterThan(1)        // or "increasing" is vacuous
      for (let i = 1; i < gaps.length; i += 1) expect(gaps[i]).toBeGreaterThan(gaps[i - 1])
    })
  }

  it('recovers once the endpoint answers again', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
    subscribeJobs(null, vi.fn(), { intervalMs: 1000, onError: vi.fn() })
    await flush()
    getJobs.mockRejectedValue(new Error('down'))

    await vi.advanceTimersByTimeAsync(1100)
    const afterFirstFailure = getJobs.mock.calls.length

    getJobs.mockResolvedValue({ workers: 1, jobs: [] })
    // Comfortably past MAX_BACKOFF (60000), so this cannot depend on where in the curve we are.
    await vi.advanceTimersByTimeAsync(60000)
    expect(getJobs.mock.calls.length).toBeGreaterThan(afterFirstFailure)
  })
})
