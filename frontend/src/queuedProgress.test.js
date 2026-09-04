import { describe, it, expect } from 'vitest'
import { queuedProgress } from './queuedProgress.js'

// See queuedProgress.js's own header for the incident this fixes: the durable scan path
// inferred phase purely from scan_runs.files/files_done, which jumped straight to 'analysing'
// the instant any file was listed — skipping listing/metadata/classifying/lifecycle, and never
// surfacing the live counters api/handlers.py's _listing_progress/_lc_progress already compute.

describe('queuedProgress — no live job state (job is null/undefined)', () => {
  it('reports queued while the job has not been claimed yet', () => {
    const g = { run: { status: 'queued' } }
    expect(queuedProgress(g, 3, null)).toEqual({ phase: 'queued', elapsed: 3, started_at: undefined })
  })

  it('threads the real enqueue timestamp through so a refresh does not reset the wait clock', () => {
    // store.pre_create_queued_scan stamps started_at at the true enqueue instant. Without this,
    // DiscoverRunProgress's "Created Ns ago" would fall back to component-mount-relative elapsed
    // on every page reload — showing "0s ago" for a scan that has actually been queued for
    // minutes. Found live 2026-08-28 alongside the missing distinct queued card.
    const g = { run: { status: 'queued', started_at: '2026-08-28T04:00:00Z' } }
    expect(queuedProgress(g, 3, null)).toEqual(
      { phase: 'queued', elapsed: 3, started_at: '2026-08-28T04:00:00Z' })
  })

  it('reports discovering before any file has been listed', () => {
    const g = { run: { status: 'running', files: 0, started_at: '2026-09-04T17:54:55Z' } }
    expect(queuedProgress(g, 5, null)).toEqual({
      phase: 'discovering', elapsed: 5, started_at: '2026-09-04T17:54:55Z',
    })
  })

  it('falls back to the coarse analysing/scoring split once files exist', () => {
    const g = { run: { status: 'running', files: 10, files_done: 4 } }
    const p = queuedProgress(g, 12, null)
    expect(p.phase).toBe('analysing')
    expect(p.files_found).toBe(10)
    expect(p.files_done).toBe(4)
    expect(p.pct).toBeGreaterThan(12)
    expect(p.pct).toBeLessThan(95)
  })

  it('reports scoring once every file is done', () => {
    const g = { run: { status: 'running', files: 10, files_done: 10 } }
    expect(queuedProgress(g, 20, null).phase).toBe('scoring')
  })

  it('tolerates a missed getScan poll (g is null) the same as no job', () => {
    expect(queuedProgress(null, 1, null)).toEqual({ phase: 'discovering', elapsed: 1, started_at: null })
  })
})

describe('queuedProgress — live job state available', () => {
  const run = { status: 'running', files: 1041, files_done: 0 }

  it('prefers the job phase over the run-derived one, even when run.files is already set', () => {
    // Without the job, run.files=1041 alone would force phase 'analysing' (the exact bug this
    // fixes) — the job says the real backend step is still 'lifecycle'.
    const job = { phase: 'lifecycle', files_found: 1041, files_evaluated: 400, rules_enabled: 3 }
    const p = queuedProgress({ run }, 40, job)
    expect(p.phase).toBe('lifecycle')
    expect(p.files_evaluated).toBe(400)
    expect(p.rules_enabled).toBe(3)
  })

  it('passes every job field through untouched — new stats need no threading here', () => {
    const job = { phase: 'lifecycle', archive_candidates: 12, delete_candidates: 3, files_tagged: 7 }
    const p = queuedProgress({ run }, 40, job)
    expect(p.archive_candidates).toBe(12)
    expect(p.delete_candidates).toBe(3)
    expect(p.files_tagged).toBe(7)
  })

  it('ignores a job still in the pre-claim "queued" phase — that is not live progress', () => {
    const job = { phase: 'queued' }
    const p = queuedProgress({ run: { status: 'running', files: 0 } }, 2, job)
    expect(p).toEqual({ phase: 'discovering', elapsed: 2 })
  })

  it('ignores a job with no phase at all', () => {
    const job = { files_found: 5 }
    const p = queuedProgress({ run: { status: 'running', files: 0 } }, 2, job)
    expect(p.phase).toBe('discovering')
  })

  it('attaches elapsed, outcomes, files and inventory the same way as the no-job path', () => {
    const g = { run: { ...run, started_at: '2026-09-04T17:54:55Z', scope: { inventory: { discovered: 1041 } } }, files: [{ file: 'a.pdf' }] }
    const job = { phase: 'listing', files_found: 300 }
    const p = queuedProgress(g, 9, job)
    expect(p.elapsed).toBe(9)
    expect(p.files).toEqual([{ file: 'a.pdf' }])
    expect(p.inventory).toEqual({ discovered: 1041 })
    expect(p.started_at).toBe('2026-09-04T17:54:55Z')
  })
})
