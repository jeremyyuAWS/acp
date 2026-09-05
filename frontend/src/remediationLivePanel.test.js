import { describe, expect, it } from 'vitest'
import { activityBuckets, attemptStage, milestoneCrossings, retrySeconds } from './remediationLivePanel.js'

describe('remediation live-panel detail', () => {
  it('places durable worker phases in the matching visual column', () => {
    expect(attemptStage('applying approved fixes')).toBe('applying')
    expect(attemptStage('re-verifying the corrected copy')).toBe('rechecking')
    expect(attemptStage('storing the corrected copy')).toBe('saving')
    expect(attemptStage('finalizing evidence')).toBe('finalizing')
  })

  it('emits only meaningful milestones crossed by a later snapshot', () => {
    const before = { run_id: 'r', total_documents: 100, documents: { completed: 49 }, delivery: { delivered: 0 } }
    const after = { run_id: 'r', total_documents: 100, documents: { completed: 51 }, delivery: { delivered: 1 } }
    expect(milestoneCrossings(before, after).map((item) => item.key))
      .toEqual(['first-delivery', 'completed-50', 'halfway'])
    expect(milestoneCrossings(null, after)).toEqual([])
    expect(milestoneCrossings(before, { ...after, run_id: 'another' })).toEqual([])
  })

  it('counts event density in twelve five-second buckets without calling it progress', () => {
    const end = '2026-09-05T12:01:00Z'
    const buckets = activityBuckets([
      { occurredAt: '2026-09-05T12:00:04Z' },
      { occurredAt: '2026-09-05T12:00:56Z' },
      { occurredAt: '2026-09-05T12:00:58Z' },
      { occurredAt: '2026-09-05T11:59:00Z' },
    ], end)
    expect(buckets).toHaveLength(12)
    expect(buckets.reduce((sum, value) => sum + value, 0)).toBe(3)
    expect(buckets.at(-1)).toBe(2)
  })

  it('shows a bounded retry countdown and never a negative value', () => {
    const now = Date.parse('2026-09-05T12:00:00Z')
    expect(retrySeconds('2026-09-05T12:00:14Z', now)).toBe(14)
    expect(retrySeconds('2026-09-05T11:59:00Z', now)).toBe(0)
    expect(retrySeconds(null, now)).toBeNull()
  })
})
