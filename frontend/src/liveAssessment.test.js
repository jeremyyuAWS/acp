import { describe, it, expect } from 'vitest'
import { normalizeLive, isNewerFrame } from './liveAssessment.js'

const full = {
  available: true, active: true, phase: 'assessing', source: 'onedrive', run_id: 'r1',
  totals: { discovered: 819, eligible: 512 },
  kpis: { completed: 145, processing: 105, findings_so_far: 47, need_attention: 22, unable_to_assess: 3 },
  outcomes: { passed: 120, review: 22, failed: 3, processing: 105 },
  queue: {
    in_flight: 6, queued: 99, workers: { busy: 6, max: 8, idle: 2 },
    current: { file: 'discharge.pdf', criterion: '1.4.3', criterion_name: 'Contrast (Minimum)',
               action: 'assessing', text: 'Assessing discharge.pdf for 1.4.3  (+5 more in progress)' },
    processing: true, stale: false,
  },
  sequence: 12, generated_at: '2026-08-20T00:00:00Z', kpis_pending: [],
}

describe('normalizeLive', () => {
  it('maps a full snapshot into KPI cards, queue and totals', () => {
    const m = normalizeLive(full)
    expect(m.available).toBe(true)
    expect(m.phaseLabel).toBe('Assessing')
    expect(m.totals).toEqual({ discovered: 819, eligible: 512 })
    expect(m.kpiCards.map((c) => [c.key, c.value, c.pending])).toEqual([
      ['completed', 145, false], ['processing', 105, false], ['findings_so_far', 47, false],
      ['need_attention', 22, false], ['unable_to_assess', 3, false],
    ])
    // Provisional (grows during the run → must carry a "so far" qualifier): findings + need-attention.
    expect(m.kpiCards.filter((c) => c.provisional).map((c) => c.key))
      .toEqual(['findings_so_far', 'need_attention'])
    expect(m.queue.inFlight).toBe(6)
    expect(m.queue.queued).toBe(99)
    expect(m.queue.workers).toEqual({ busy: 6, max: 8, idle: 2 })
    expect(m.queue.current.criterionName).toBe('Contrast (Minimum)')
    expect(m.queue.processing).toBe(true)
    expect(m.warnings).toEqual([])
  })

  it('treats an absent queue block as PENDING, not zero (independent-merge backend)', () => {
    const m = normalizeLive({ ...full, queue: undefined, kpis_pending: ['queue'] })
    expect(m.queue).toBeNull()                                   // no fabricated "0 workers"
    expect(m.warnings.some((w) => /coming online/i.test(w))).toBe(true)
  })

  it('marks an individual pending KPI so the card can show a dash, not a false 0', () => {
    const m = normalizeLive({ ...full, kpis: { completed: 145 }, kpis_pending: ['need_attention'] })
    const na = m.kpiCards.find((c) => c.key === 'need_attention')
    expect(na.pending).toBe(true)
  })

  it('a stale queue reads as paused, not busy — current cleared, warning added', () => {
    const m = normalizeLive({ ...full, queue: { ...full.queue, stale: true } })
    expect(m.queue.stale).toBe(true)
    expect(m.queue.processing).toBe(false)
    expect(m.queue.current).toBeNull()                          // don't show a frozen "in flight"
    expect(m.queue.laneLabel).toMatch(/paused|between phases/i)
    expect(m.warnings.some((w) => /no worker/i.test(w))).toBe(true)
  })

  it('an unavailable or empty snapshot is a safe empty model', () => {
    for (const raw of [null, undefined, { available: false }]) {
      const m = normalizeLive(raw)
      expect(m.available).toBe(false)
      expect(m.kpiCards).toEqual([])
      expect(m.queue).toBeNull()
    }
  })
})

describe('isNewerFrame (reconnect ordering)', () => {
  it('accepts a higher sequence and rejects a stale/out-of-order one', () => {
    expect(isNewerFrame(5, 6)).toBe(true)
    expect(isNewerFrame(6, 5)).toBe(false)
    expect(isNewerFrame(6, 6)).toBe(false)
  })
  it('accepts any frame when either side has no sequence (best-effort)', () => {
    expect(isNewerFrame(undefined, 3)).toBe(true)
    expect(isNewerFrame(3, undefined)).toBe(true)
  })
})
