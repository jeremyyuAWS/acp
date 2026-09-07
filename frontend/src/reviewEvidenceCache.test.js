import { describe, expect, it, vi } from 'vitest'
import { createReviewEvidenceCache } from './reviewEvidenceCache.js'

describe('review evidence request coordination', () => {
  it('shares one request for the same workflow revision and refreshes explicitly', async () => {
    const fetcher = vi.fn(async () => ({ timed_reviews: 3, median_review_ms: 4000 }))
    const cache = createReviewEvidenceCache(fetcher)
    const [a, b] = await Promise.all([cache.load('scan-1', 4), cache.load('scan-1', 4)])
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(a).toBe(b)
    await cache.load('scan-1', 4, { refresh: true })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('gives different revisions different identities even when responses race', async () => {
    const releases = {}
    const cache = createReviewEvidenceCache((scan) => new Promise((resolve) => { releases[scan] = resolve }))
    const oldRequest = cache.load('old-scan', 7)
    const newRequest = cache.load('new-scan', 8)
    releases['new-scan']({ median_review_ms: 2000 })
    releases['old-scan']({ median_review_ms: 9000 })
    const [oldResult, newResult] = await Promise.all([oldRequest, newRequest])
    expect(oldResult.key).toBe('old-scan:7')
    expect(newResult.key).toBe('new-scan:8')
    expect(newResult.id).toBeGreaterThan(oldResult.id)
  })

  it('does not retain a failed request', async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ median_review_ms: 3000 })
    const cache = createReviewEvidenceCache(fetcher)
    await expect(cache.load('scan-1', 1)).rejects.toThrow('offline')
    await expect(cache.load('scan-1', 1)).resolves.toMatchObject({ value: { median_review_ms: 3000 } })
  })
})
