import { afterEach, describe, expect, it, vi } from 'vitest'
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.resetModules() })
async function setup(response = { ok: true, json: async () => ({}) }) {
  vi.stubEnv('VITE_SIM', 'false'); vi.resetModules()
  const fetch = vi.fn().mockResolvedValue(response); vi.stubGlobal('fetch', fetch)
  const api = await import('./api.js'); api.setMsToken('fixture-token')
  return { api, fetch }
}
describe('analytics reporting transport', () => {
  it('encodes cross-user filters and forwards cancellation with signed-in identity', async () => {
    const { api, fetch } = await setup(); const signal = new AbortController().signal
    await api.getAdminAnalytics('custom', 'sharepoint', { owner: 'alice+ops@example.com', status: 'failed', search: 'run & source', start: '2026-09-01T00:00:00Z', end: '2026-09-14T00:00:00Z', timezone: 'America/Los_Angeles', page: 2, page_size: 25, basis: 'results', signal })
    const [url, request] = fetch.mock.lastCall; const query = new URL(url).searchParams
    expect(query.get('owner')).toBe('alice+ops@example.com'); expect(query.get('search')).toBe('run & source')
    expect(query.get('timezone')).toBe('America/Los_Angeles'); expect(query.get('page')).toBe('2'); expect(query.get('page_size')).toBe('25'); expect(query.get('signal')).toBeNull()
    expect(query.get('basis')).toBe('results')
    expect(request).toMatchObject({ signal, cache: 'no-store', headers: { Authorization: 'Bearer fixture-token', 'X-Auth-Provider': 'microsoft' } })
    await api.getAdminAnalyticsScan('run/with space', { signal })
    expect(fetch.mock.lastCall[0]).toContain('/admin/analytics/scans/run%2Fwith%20space'); expect(fetch.mock.lastCall[1].signal).toBe(signal)
  })
  it('does not download a failed export or conceal an authorization error', async () => {
    const { api } = await setup({ ok: false, status: 403, statusText: 'Forbidden', json: async () => ({ detail: 'admin access required' }) })
    await expect(api.downloadAdminAnalyticsExport('all', null, {})).rejects.toThrow('admin access required')
  })
})
