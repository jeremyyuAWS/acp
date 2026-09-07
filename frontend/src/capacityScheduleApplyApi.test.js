/** The capacity schedule apply call is a real, potentially expensive Azure mutation. */
import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('applyCapacitySchedule', () => {
  it('posts the reviewed version and reason with a bounded request', async () => {
    vi.stubEnv('VITE_SIM', 'false')
    vi.stubEnv('VITE_API', 'https://api.example.test')
    const fetchMock = vi.fn(() => Promise.resolve({
      ok: true, status: 200, headers: new Headers(),
      json: () => Promise.resolve({ schedule_version: 7, application: { state: 'applied' } }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    const { applyCapacitySchedule, CAPACITY_APPLY_TIMEOUT_MS } = await import('./api.js')
    const result = await applyCapacitySchedule({ version: 7, reason: 'approved rollout' })

    expect(result.application.state).toBe('applied')
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, request] = fetchMock.mock.calls[0]
    expect(url).toBe('https://api.example.test/control/capacity-schedule/apply')
    expect(request.method).toBe('POST')
    expect(request.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(request.body)).toEqual({ version: 7, reason: 'approved rollout' })
    expect(request.signal).toBeInstanceOf(AbortSignal)
    expect(CAPACITY_APPLY_TIMEOUT_MS).toBeGreaterThanOrEqual(30_000)
  })

  it('does not contact Azure in the simulated build or claim that it applied', async () => {
    vi.stubEnv('VITE_SIM', 'true')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const { applyCapacitySchedule } = await import('./api.js')
    const result = await applyCapacitySchedule({ version: 4, reason: 'demo review' })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      simulated: true,
      schedule_version: 4,
      application: { state: 'not_applied', applied_version: null },
    })
  })
})
