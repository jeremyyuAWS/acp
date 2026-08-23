/**
 * The audit trail's read must not manufacture an empty history.
 *
 * `api.getDocumentTimeline` used to end in `.catch(() => [])`, which is the right trade for the
 * best-effort panels around it and the wrong one here: an audit trail rendered from `[]` says
 * "nothing has happened to this document", and a transport failure is not entitled to say that.
 * The two states are different sentences, and until this change the client could not tell them
 * apart at all. These guard the distinction at the api layer, where it is decided.
 *
 * Sibling: documentAudit.test.jsx / fileDrawerTimeline.test.jsx cover what the two callers then
 * DO with the rejection. This file is only about which of the two answers the API hands back.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// api.js short-circuits to canned data when SIM is on; these are about the real fetch path.
vi.mock('./sim.js', async (o) => ({ ...(await o()), SIM: false }))

const { getDocumentTimeline } = await import('./api.js')

const resp = (status, body) => ({
  ok: status < 400, status, statusText: '', url: 'http://localhost:8077/scans/s1/timeline?file=a.docx',
  headers: { get: () => null },
  json: async () => body,
})

afterEach(() => { vi.unstubAllGlobals() })
beforeEach(() => { vi.unstubAllGlobals() })

describe('getDocumentTimeline — a failed read is not an empty history', () => {
  it('rejects on a server error instead of resolving to []', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(resp(500, { detail: 'timeline unavailable' })))
    await expect(getDocumentTimeline('s1', 'a.docx')).rejects.toThrow(/timeline unavailable/)
  })

  it('rejects on a network failure instead of resolving to []', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new Error('NetworkError')))
    await expect(getDocumentTimeline('s1', 'a.docx')).rejects.toThrow(/NetworkError/)
  })

  it('a document with a genuinely empty history still resolves to []', async () => {
    // The honest empty: the server answered, and the answer was "no events". This is the case
    // the rejection above must stay distinguishable from.
    vi.stubGlobal('fetch', () => Promise.resolve(resp(200, [])))
    await expect(getDocumentTimeline('s1', 'a.docx')).resolves.toEqual([])
  })

  it('resolves with the recorded events when there are some', async () => {
    const rows = [{ ts: '2026-08-20T10:00:00Z', kind: 'scan', title: 'Scan started (drive)' }]
    vi.stubGlobal('fetch', () => Promise.resolve(resp(200, rows)))
    await expect(getDocumentTimeline('s1', 'a.docx')).resolves.toEqual(rows)
  })

  it('resolves to [] without calling fetch when there is no scan or file to ask about', async () => {
    // Not a failure and not a claim about a document — there is no document. Kept resolving so a
    // caller with nothing selected renders nothing rather than an error.
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    await expect(getDocumentTimeline(null, 'a.docx')).resolves.toEqual([])
    await expect(getDocumentTimeline('s1', null)).resolves.toEqual([])
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
