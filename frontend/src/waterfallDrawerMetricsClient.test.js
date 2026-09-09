import { afterEach, expect, it, vi } from 'vitest'
vi.mock('./api.js', () => ({ getRealtimeStreamRequest: () => ({ headers: { 'x-sp-token': 'fixture-provider-token' } }) }))
vi.mock('./sim.js', () => ({ SIM: false }))
import { getWaterfallDrawerMetrics } from './waterfallDrawerMetricsClient.js'
import { noteAuthChange, _resetAuthEpoch } from './apiIdentity.js'
afterEach(() => { vi.unstubAllGlobals(); _resetAuthEpoch() })
const scope = { stage: 'fallback_2', provider: 'provider', model: 'exact-model' }
it('uses bounded metrics and exact stage/model identity with provider authentication', async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ scan_id: 's', batch_id: 'b', scope }) }))
  vi.stubGlobal('fetch', fetch)
  const controller = new AbortController()
  await getWaterfallDrawerMetrics('s', 'b', scope, controller.signal)
  expect(fetch.mock.calls[0][0]).toContain('/s/remediation/waterfall/b/metrics?stage=fallback_2&provider=provider&model=exact-model')
  expect(fetch.mock.calls[0][1]).toMatchObject({ headers: { 'x-sp-token': 'fixture-provider-token' }, signal: controller.signal, cache: 'no-store' })
})
it('rejects account or stage changes rather than showing broader evidence', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ scan_id: 's', batch_id: 'b', scope: { ...scope, stage: 'primary' } }) })))
  await expect(getWaterfallDrawerMetrics('s', 'b', scope)).rejects.toThrow('stage changed')
  vi.stubGlobal('fetch', vi.fn(async () => { noteAuthChange('one', 'two'); return { ok: true, json: async () => ({ scan_id: 's', batch_id: 'b', scope }) } }))
  await expect(getWaterfallDrawerMetrics('s', 'b', scope)).rejects.toThrow('account')
})
