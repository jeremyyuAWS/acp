import { describe, it, expect } from 'vitest'
import { pickDefaultScan } from './defaultScan.js'

// scans arrive newest-first (list_scans ORDER BY completed_at DESC).
const scan = (id, files, published_at = null) => ({ id, files, published_at })

describe('pickDefaultScan', () => {
  it('skips a collapsed newest scan and falls back to the most recent full-size one', () => {
    // newest is 5 docs on top of a 22-doc estate — the production-probe fingerprint.
    const list = [scan('new', 5), scan('real', 22), scan('older', 20)]
    expect(pickDefaultScan(list).id).toBe('real')
  })

  it('skips consecutive collapsed scans, not just the first', () => {
    const list = [scan('a', 1), scan('b', 2), scan('full', 30), scan('c', 28)]
    expect(pickDefaultScan(list).id).toBe('full')
  })

  it('keeps the newest when it is full-size', () => {
    const list = [scan('new', 24), scan('old', 22)]
    expect(pickDefaultScan(list).id).toBe('new')
  })

  it('never hides a legitimately small estate (no larger sibling to compare against)', () => {
    // all scans are small — nothing is "collapsed" relative to the others, so newest wins.
    const list = [scan('new', 3), scan('old', 4), scan('older', 2)]
    expect(pickDefaultScan(list).id).toBe('new')
  })

  it('uses exactly the monitor threshold (< 0.5 * biggest is collapsed, == is kept)', () => {
    expect(pickDefaultScan([scan('n', 11), scan('big', 22)]).id).toBe('n')   // 11 == 0.5*22 → kept
    expect(pickDefaultScan([scan('n', 10), scan('big', 22)]).id).toBe('big') // 10 < 11 → skipped
  })

  it('only considers the recent window, so an ancient huge scan does not condemn the present', () => {
    const recent = Array.from({ length: 10 }, (_, i) => scan(`r${i}`, 20))
    const list = [...recent, scan('ancient', 500)]
    expect(pickDefaultScan(list).id).toBe('r0')          // window is the first 10; ancient excluded
  })

  it('degrades safely on empty / missing counts', () => {
    expect(pickDefaultScan([])).toBeNull()
    expect(pickDefaultScan(null)).toBeNull()
    expect(pickDefaultScan([scan('a')]).id).toBe('a')    // files undefined → newest
  })

  it('prefers a published scan over an unpublished one of similar size', () => {
    // Both pass the collapse check; the published one should win even if newer unpublished exists.
    const list = [scan('new-unpub', 20), scan('old-pub', 22, '2026-08-01T00:00:00Z')]
    expect(pickDefaultScan(list).id).toBe('old-pub')
  })

  it('still applies collapse check before published preference', () => {
    // A published but collapsed scan loses to a larger unpublished one above the floor.
    const list = [scan('small-pub', 5, '2026-08-01T00:00:00Z'), scan('big-unpub', 22)]
    expect(pickDefaultScan(list).id).toBe('big-unpub')
  })
})
