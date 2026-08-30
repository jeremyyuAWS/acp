/**
 * getScan(id, knownRevision) — conditional fetch against the backend's ETag support
 * (api/routes/scans.py's GET /scans/{sid}).
 *
 * A caller already holding `run.revision` can pass it as knownRevision to send
 * `If-None-Match: W/"<revision>"`. The backend answers 304 with no body when nothing changed,
 * saving the cost of recomputing/reshipping the full file_records+issue_records join. These
 * tests pin the client half: the header is sent only when a revision is supplied, and a 304
 * resolves to NOT_MODIFIED rather than throwing (so a caller must opt in by checking the return
 * value — the plain single-argument call is unaffected).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))

const { getScan, NOT_MODIFIED, setGoogleToken } = await import('./api.js')

const BASE = 'http://localhost:8077'
const SID = 'a242d0f5f635'

const ok = (body) => ({
  ok: true, status: 200, statusText: 'OK', url: `${BASE}/scans/${SID}`,
  headers: { get: (k) => (k.toLowerCase() === 'etag' ? 'W/"1"' : null) },
  json: async () => body,
})
const notModified = () => ({
  ok: false, status: 304, statusText: 'Not Modified', url: `${BASE}/scans/${SID}`,
  headers: { get: () => null },
  json: async () => { throw new Error('304 has no body') },
})

beforeEach(() => { setGoogleToken('token') })
afterEach(() => { vi.unstubAllGlobals() })

describe('no knownRevision — unchanged from before', () => {
  it('sends no If-None-Match header', async () => {
    const fetchMock = vi.fn(async () => ok({ run: { id: SID } }))
    vi.stubGlobal('fetch', fetchMock)

    await getScan(SID)

    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.headers['If-None-Match']).toBeUndefined()
  })
})

describe('knownRevision supplied', () => {
  it('sends If-None-Match as a weak ETag of the revision', async () => {
    const fetchMock = vi.fn(async () => ok({ run: { id: SID } }))
    vi.stubGlobal('fetch', fetchMock)

    await getScan(SID, 3)

    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.headers['If-None-Match']).toBe('W/"3"')
  })

  it('a 304 resolves to NOT_MODIFIED rather than throwing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => notModified()))

    await expect(getScan(SID, 1)).resolves.toBe(NOT_MODIFIED)
  })

  it('a 200 (stale revision) resolves to the fresh payload as usual', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ run: { id: SID, revision: 2 } })))

    await expect(getScan(SID, 1)).resolves.toEqual({ run: { id: SID, revision: 2 } })
  })
})
