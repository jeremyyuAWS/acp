import { describe, it, expect, afterEach, vi } from 'vitest'

vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))

const { getRemediationStatus, setGoogleToken } = await import('./api.js')

afterEach(() => { vi.unstubAllGlobals() })

describe('live Remediate progress freshness', () => {
  it('bypasses browser caches when polling the remaining job count', async () => {
    setGoogleToken('token')
    const fetchMock = vi.fn(async () => ({
      ok: true, status: 200, statusText: 'OK', url: 'http://localhost/remediation-status',
      json: async () => ({ in_flight: 7, failed: 0 }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    await getRemediationStatus('scan-1')

    expect(fetchMock.mock.calls[0][1].cache).toBe('no-store')
  })
})
