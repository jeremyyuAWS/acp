/**
 * EventSource-based discovery progress stream wiring in App.jsx.
 *
 * The thread-based (non-queued) scan path opens an EventSource on the job-scoped SSE URL
 * instead of polling GET /scans/jobs/{id} on a timer. Source assertions here guard the wiring
 * because the integration point is App.jsx's closures — not a module that can be imported and
 * driven in isolation — and a silent revert would re-introduce the 350 ms polling loop with no
 * failing test.
 *
 * The durable-queue and reconnect paths delegate to openDiscoverStream (added by #843) which
 * opens the scan-scoped SSE URL; those paths' SSE wiring is covered by openDiscoverStream's
 * own tests.
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
