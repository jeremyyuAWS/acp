/**
 * GET /workspace/bootstrap — the real (non-SIM) fetch path. Split from workspaceBootstrap
 * .test.js because vi.mock('./sim.js', ...) hoists to the top of this module and would flip SIM
 * off for the whole file (see scanUnavailable.test.js for the established convention).
 */
import { describe, it, expect, afterEach, vi } from 'vitest'

vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))

const { getWorkspaceBootstrap, setGoogleToken } = await import('./api.js')

afterEach(() => { vi.unstubAllGlobals() })

describe('api.js getWorkspaceBootstrap — real mode', () => {
  it('fetches GET /workspace/bootstrap and returns the parsed body', async () => {
    setGoogleToken('token')
    const body = { me: { email: 'a@b.com', is_scope_owner: true, is_admin: true },
                   scan_id: 's1', scan_status: 'done', revision: 3,
                   overview: { estate: { discovered: 5 }, documents: { certifiable: 4 } },
                   scans: [{ id: 's1' }], active_job: {} }
    const fetchMock = vi.fn(async (url) => ({ ok: true, url, json: async () => body }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getWorkspaceBootstrap()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/workspace\/bootstrap$/)
    expect(result).toEqual(body)
  })
})
