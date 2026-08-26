/**
 * EventSource-based discovery progress stream wiring in App.jsx.
 *
 * The thread-based (non-queued) scan path and the durable-queue path both now open an
 * EventSource instead of polling GET /scans/jobs/{id} on a timer. Source assertions here
 * guard the wiring because the integration point is App.jsx's closures — not a module that
 * can be imported and driven in isolation — and a silent revert would re-introduce the 350 ms
 * polling loop with no failing test.
 *
 * Behavioural truth: the backend tests (test_job_state_cross_replica.py) pin the SSE endpoint
 * contract (correct state, seq changes, done event); these pin that the frontend actually
 * connects to it.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const src = () => readFileSync(join(HERE, 'App.jsx'), 'utf8')

describe('non-queued (thread) scan path', () => {
  it('opens EventSource on the job-scoped SSE URL', () => {
    expect(src()).toMatch(/new EventSource\(`\/scans\/jobs\/\$\{job_id\}\/stream`\)/)
  })

  it('falls back to polling when EventSource is not available in the environment', () => {
    expect(src()).toMatch(/typeof EventSource !== 'undefined'/)
    expect(src()).toMatch(/_pollScanJobPolling/)
  })

  it('falls back to polling (not rejects) on a connection-level error', () => {
    // e.data is null/undefined for browser-fired connection errors; server-sent event: error
    // carries e.data. The handler distinguishes them and falls back to polling for the former.
    expect(src()).toMatch(/_pollScanJobPolling\(job_id\)\.then\(resolve, reject\)/)
  })

  it('closes the EventSource in the finally block so it never leaks on error or done', () => {
    expect(src()).toMatch(/run\.finally\(/)
  })
})

describe('queued (durable) scan path', () => {
  it('opens EventSource on the scan-scoped SSE URL', () => {
    expect(src()).toMatch(/new EventSource\(`\/scans\/\$\{scan_id\}\/discover\/stream`\)/)
  })

  it('uses SSE job state and only falls back to fetching job_id when SSE has not connected', () => {
    expect(src()).toMatch(/sseJob \?\?/)
  })

  it('closes the EventSource via finally when the scan loop exits for any reason', () => {
    expect(src()).toMatch(/sseEs\?\.close\(\)/)
  })
})

describe('reconnect path (scan_id known from sessionStorage)', () => {
  it('also opens the scan-scoped SSE URL — at least two usages total', () => {
    const usages = src().match(/new EventSource\(`\/scans\/\$\{scan_id\}\/discover\/stream`\)/g) || []
    expect(usages.length).toBeGreaterThanOrEqual(2)
  })
})
