import { afterEach, expect, it, vi } from 'vitest'
import { getWaterfall } from './remediationWaterfallClient.js'
import { noteAuthChange, _resetAuthEpoch } from './apiIdentity.js'
vi.mock('./sim.js', () => ({ SIM: false }))
vi.mock('./api.js', () => ({ getRealtimeStreamRequest: () => ({ headers: { Authorization: 'Bearer fixture', 'X-Auth-Provider': 'microsoft' } }) }))
afterEach(() => { vi.unstubAllGlobals(); _resetAuthEpoch() })
it('uses authenticated Microsoft headers and performs only a no-store read', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ scan_id: 'scan/a', batch_id: 'batch/b' }) })
  vi.stubGlobal('fetch', fetch)
  await getWaterfall('scan/a', 'batch/b')
  const [url, options] = fetch.mock.calls[0]
  expect(url).toContain('/scans/scan%2Fa/remediation/waterfall/batch%2Fb')
  expect(options.headers['X-Auth-Provider']).toBe('microsoft')
  expect(options.cache).toBe('no-store')
  expect(options.method).toBeUndefined()
  expect(options.body).toBeUndefined()
})
it('rejects a mismatched run and a response from the previous account', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ scan_id: 'scan', batch_id: 'different' }) }))
  await expect(getWaterfall('scan', 'batch')).rejects.toThrow('Run changed')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => { noteAuthChange('old', 'new'); return { scan_id: 'scan', batch_id: 'batch' } } }))
  await expect(getWaterfall('scan', 'batch')).rejects.toThrow('Account changed')
})
