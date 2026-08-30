/**
 * getQueueEstimate(scanId, kind) — the client wrapper around GET /scans/{sid}/queue-estimate,
 * backing the "Estimated pickup" fact in each tab's Processing status panel
 * (discoverProcessingState.js's own tests pin what happens to the response once it arrives).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))

const { getQueueEstimate, setGoogleToken } = await import('./api.js')

const BASE = 'http://localhost:8077'
const SID = 'a242d0f5f635'

beforeEach(() => { setGoogleToken('token') })
afterEach(() => { vi.unstubAllGlobals() })

it('requests the given kind as a query param', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true, status: 200, statusText: 'OK', url: `${BASE}/scans/${SID}/queue-estimate?kind=remediate`,
    headers: { get: () => null },
    json: async () => ({ available: false }),
  }))
  vi.stubGlobal('fetch', fetchMock)

  await getQueueEstimate(SID, 'remediate')

  const [url] = fetchMock.mock.calls[0]
  expect(url).toBe(`${BASE}/scans/${SID}/queue-estimate?kind=remediate`)
})

it('resolves the response as-is, whatever shape the route sends', async () => {
  const body = { available: true, state: 'estimated', earliest_at: '2026-08-30T00:02:00Z',
                 latest_at: '2026-08-30T00:04:00Z', confidence: 'medium' }
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, statusText: 'OK', url: `${BASE}/scans/${SID}/queue-estimate?kind=discover`,
    headers: { get: () => null },
    json: async () => body,
  })))

  await expect(getQueueEstimate(SID, 'discover')).resolves.toEqual(body)
})
