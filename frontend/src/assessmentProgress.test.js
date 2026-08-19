// Outcome-oriented progress view-model (Track A of the progress redesign). The two honesty rules
// are the load-bearing assertions: the percentage is completed-with-saved-results (never downloads),
// and rate/ETA are null until there is a real signal rather than a fabricated "2 minutes left".
import { describe, it, expect } from 'vitest'
import { assessmentProgress, assessmentLine, etaText } from './assessmentProgress.js'

describe('assessmentProgress', () => {
  it('is null for no payload', () => {
    expect(assessmentProgress(null)).toBe(null)
  })

  it('percent is completed / total, and completed is clamped to total', () => {
    expect(assessmentProgress({ phase: 'analysing', files_found: 250, files_done: 145 }).percent).toBe(58)
    // A stray over-count never shows > 100%.
    const vm = assessmentProgress({ phase: 'analysing', files_found: 250, files_done: 300 })
    expect(vm.completed).toBe(250)
    expect(vm.percent).toBe(100)
  })

  it('derives rate and ETA only once there is a signal (completed > 0 AND elapsed > 0)', () => {
    // 90 done in 300s = 18/min; 160 remaining at 18/min ≈ 533s.
    const vm = assessmentProgress({ phase: 'analysing', files_found: 250, files_done: 90, elapsed: 300 })
    expect(vm.ratePerMin).toBe(18)
    expect(vm.etaSeconds).toBeGreaterThan(500)
    expect(vm.etaSeconds).toBeLessThan(560)
    expect(vm.etaText).toMatch(/about 9 minutes/)
  })

  it('gives no rate or ETA before a real signal — never a guess', () => {
    expect(assessmentProgress({ phase: 'analysing', files_found: 250, files_done: 0, elapsed: 10 }).ratePerMin).toBe(null)
    expect(assessmentProgress({ phase: 'analysing', files_found: 250, files_done: 5, elapsed: 0 }).ratePerMin).toBe(null)
    expect(assessmentProgress({ phase: 'analysing', files_found: 250, files_done: 5 }).etaSeconds).toBe(null)
  })

  it('ETA is 0 when the count is known and everything is done', () => {
    expect(assessmentProgress({ phase: 'scoring', files_found: 250, files_done: 250, elapsed: 400 }).etaSeconds).toBe(0)
  })

  it('normalizes outcome tallies, and returns null until at least one bucket is populated', () => {
    expect(assessmentProgress({ phase: 'analysing', files_found: 10, files_done: 3 }).outcomes).toBe(null)
    expect(assessmentProgress({ phase: 'analysing', files_found: 10, files_done: 3, outcomes: { passed: 0, review: 0, skipped: 0, processing: 0 } }).outcomes).toBe(null)
    expect(assessmentProgress({ phase: 'analysing', files_found: 10, files_done: 3, outcomes: { passed: 2, review: 1 } }).outcomes)
      .toEqual({ passed: 2, review: 1, skipped: 0, processing: 0 })
  })
})

describe('etaText', () => {
  it('reads for a human and refuses to guess', () => {
    expect(etaText(null)).toBe(null)
    expect(etaText(0)).toBe(null)
    expect(etaText(30)).toBe('less than a minute')
    expect(etaText(360)).toBe('about 6 minutes')
    expect(etaText(60)).toBe('about 1 minute')
    expect(etaText(3900)).toMatch(/about 1h 5m/)
  })
})

describe('assessmentLine', () => {
  it('is outcome-oriented on the per-file phases — done, rate, ETA — not one filename', () => {
    const line = assessmentLine({ phase: 'analysing', files_found: 250, files_done: 90, elapsed: 300, current: 'Doc2.pptx' })
    expect(line).toMatch(/Assessing 90 of 250 files · 36%/)
    expect(line).toMatch(/about 9 minutes left/)      // 160 remaining at 18/min ≈ 8.9 min
    expect(line).toMatch(/18\/min/)
    expect(line).not.toMatch(/Doc2\.pptx/)            // multiple files at once — no single filename
  })

  it('falls back to the plain phase label before there is a file count', () => {
    expect(assessmentLine({ phase: 'connecting', elapsed: 3 })).toMatch(/Connecting to source · still working \(3s\)/)
  })

  it('uses a phase-appropriate verb', () => {
    expect(assessmentLine({ phase: 'reading', files_found: 10, files_done: 4 })).toMatch(/^Retrieving 4 of 10/)
  })
})
