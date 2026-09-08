import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { remediationSubmissionFailureCopy } from './Remediate.jsx'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_SIM', 'false')
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

function capacityResponse(changes) {
  return {
    ok: false,
    status: 503,
    statusText: 'Service Unavailable',
    url: 'https://prod.example/api/scans/scan-147/remediate',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => ({
      code: 'DB_CAPACITY_BUSY',
      detail: 'database_busy',
      message: 'Database capacity is temporarily exhausted.',
      changes,
      request_id: 'prod-request-42',
      occurred_at: '2026-09-08T12:00:00Z',
    }),
  }
}

describe('production database saturation during remediation submission', () => {
  it('preserves the structured 503 fields needed to distinguish unknown from no changes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(capacityResponse('unknown')))
    const { remediateScan } = await import('./api.js')

    const failure = await remediateScan('scan-147', ['one.docx', 'two.pdf']).catch((err) => err)

    expect(failure).toMatchObject({
      status: 503,
      code: 'DB_CAPACITY_BUSY',
      detail: 'database_busy',
      changes: 'unknown',
      requestId: 'prod-request-42',
      occurredAt: '2026-09-08T12:00:00Z',
    })
    expect(fetch).toHaveBeenCalledOnce()
    const [url, request] = fetch.mock.calls[0]
    expect(url).toContain('/scans/scan-147/remediate')
    expect(request.method).toBe('POST')
    expect(JSON.parse(request.body)).toEqual({ scope: ['one.docx', 'two.pdf'] })
  })

  it('does not call an unknown outcome “not enqueued” and explains the safe reconciliation retry', () => {
    const message = remediationSubmissionFailureCopy(Object.assign(new Error('busy'), {
      code: 'DB_CAPACITY_BUSY', changes: 'unknown',
    }))

    expect(message).toContain('could not confirm whether')
    expect(message).toContain('retry the same selection')
    expect(message).toContain('reuse any matching work already queued')
    expect(message).not.toMatch(/not (submitted|enqueued)/i)
  })

  it('states that no submission occurred only when the server proves changes were none', () => {
    const message = remediationSubmissionFailureCopy(Object.assign(new Error('busy'), {
      code: 'DB_CAPACITY_BUSY', changes: 'none',
    }))

    expect(message).toContain('was not submitted')
    expect(message).toContain('capacity')
  })

  it('retains the ordinary endpoint reason for non-capacity failures', () => {
    expect(remediationSubmissionFailureCopy(new Error('scan not found')))
      .toBe('Could not enqueue: scan not found')
  })
})
