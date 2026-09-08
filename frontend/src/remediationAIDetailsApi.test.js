import { afterEach, beforeEach, expect, it, vi } from 'vitest'

beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_SIM', 'false') })
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals() })
const ok = body => ({ ok: true, status: 200, json: async () => body })

it('reads saved history and provenance with authentication, without generating or approving', async () => {
  const items = [{ id: 'p1', proposed_value: 'Actual stored text' }]
  vi.stubGlobal('fetch', vi.fn(async url => ok(url.includes('/hitl/') ? items : [{ id: 'c1' }])))
  const { getRemediationAIDetails, setMsToken } = await import('./api.js')
  setMsToken('test-token')
  expect(await getRemediationAIDetails('scan /1')).toEqual({ items, calls: [{ id: 'c1' }], callsAvailable: true, available: true })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls[0][0]).toContain('scan_id=scan%20%2F1&include_superseded=true')
  for (const [, options] of fetch.mock.calls) {
    expect(options.method || 'GET').toBe('GET')
    expect(options.headers.Authorization).toBe('Bearer test-token')
    expect(options.cache).toBe('no-store')
  }
})

it('keeps saved proposals visible if call history fails and marks provenance unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.includes('/ai_calls')) throw new Error('offline')
    return ok([{ id: 'p1' }])
  }))
  const { getRemediationAIDetails } = await import('./api.js')
  expect(await getRemediationAIDetails('s1')).toEqual({ items: [{ id: 'p1' }], calls: [], callsAvailable: false, available: true })
})

it('does not turn a failed or malformed suggestion response into an empty success', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.includes('/hitl/')) throw new Error('saved suggestions offline')
    return ok([])
  }))
  const { getRemediationAIDetails } = await import('./api.js')
  await expect(getRemediationAIDetails('s1')).rejects.toThrow('saved suggestions offline')
  fetch.mockImplementation(async url => ok(url.includes('/hitl/') ? {} : []))
  await expect(getRemediationAIDetails('s1')).rejects.toThrow('unavailable')
})

it('requires a run and does not fabricate saved history in demo mode', async () => {
  vi.stubEnv('VITE_SIM', 'true')
  vi.stubGlobal('fetch', vi.fn())
  const { getRemediationAIDetails } = await import('./api.js')
  await expect(getRemediationAIDetails('')).rejects.toThrow('Select an assessment')
  expect(await getRemediationAIDetails('s1')).toMatchObject({ available: false, callsAvailable: false })
  expect(fetch).not.toHaveBeenCalled()
})
