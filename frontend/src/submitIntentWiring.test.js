/**
 * The idempotency key must actually REACH the server, and a retry must reuse it.
 *
 * submitIntent.test.js proves the key module behaves; this proves it is connected. Those are
 * different claims, and the second is the one that was false: enqueue_scan has honoured an
 * Idempotency-Key header for some time while the client sent none, so the duplicate-submission
 * guarantee existed in the backend and was unreachable from the product.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

const okJson = (body) => ({ ok: true, status: 200, json: async () => body,
                            headers: { get: () => null } })

describe('startScanQueued and the Idempotency-Key header', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.stubEnv('VITE_SIM', 'false')
    try { sessionStorage.clear() } catch { /* unavailable */ }
  })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('sends the key it is given', async () => {
    const fetchMock = vi.fn(async () => okJson({ scan_id: 's1', job_id: 'j1', queued: true }))
    vi.stubGlobal('fetch', fetchMock)
    const { startScanQueued } = await import('./api.js')

    await startScanQueued('local', null, true, false, false, true, null, null, 'key-abc')

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['Idempotency-Key']).toBe('key-abc')
  })

  it('sends NO key when none is supplied, so existing callers are unchanged', async () => {
    const fetchMock = vi.fn(async () => okJson({ scan_id: 's1', job_id: 'j1', queued: true }))
    vi.stubGlobal('fetch', fetchMock)
    const { startScanQueued } = await import('./api.js')

    await startScanQueued('local')

    const [, init] = fetchMock.mock.calls[0]
    expect('Idempotency-Key' in init.headers).toBe(false)
  })

  it('reuses ONE key across a retry after an uncertain failure', async () => {
    // The sequence that produces a duplicate scan without this: submit, lose the response after
    // the server committed, submit again.
    const fetchMock = vi.fn()
      .mockImplementationOnce(async () => { throw new TypeError('Failed to fetch') })
      .mockImplementationOnce(async () => okJson({ scan_id: 's1', job_id: 'j1', queued: true }))
    vi.stubGlobal('fetch', fetchMock)
    const { startScanQueued } = await import('./api.js')
    const { beginOrResumeIntent, completeIntent, outcomeIsUncertain } =
      await import('./submitIntent.js')

    const attempt = async () => {
      const key = beginOrResumeIntent('scan')
      try {
        const r = await startScanQueued('local', null, true, false, false, true, null, null, key)
        completeIntent('scan')
        return r
      } catch (err) {
        expect(outcomeIsUncertain(err?.status)).toBe(true)   // no status on a network error
        throw err
      }
    }

    await expect(attempt()).rejects.toBeTruthy()
    await attempt()

    const keys = fetchMock.mock.calls.map(([, init]) => init.headers['Idempotency-Key'])
    expect(keys).toHaveLength(2)
    expect(keys[0]).toBe(keys[1])       // the whole point: one intent, one key
    expect(keys[0]).toBeTruthy()
  })

  it('uses a DIFFERENT key for a genuinely new submission', async () => {
    // Re-scan must start a new run, not resolve to the previous one. Keying on the request
    // parameters instead of the intent would break exactly this.
    const fetchMock = vi.fn(async () => okJson({ scan_id: 's1', job_id: 'j1', queued: true }))
    vi.stubGlobal('fetch', fetchMock)
    const { startScanQueued } = await import('./api.js')
    const { beginOrResumeIntent, completeIntent } = await import('./submitIntent.js')

    for (let i = 0; i < 2; i++) {
      const key = beginOrResumeIntent('scan')
      await startScanQueued('local', null, true, false, false, true, null, null, key)
      completeIntent('scan')
    }

    const keys = fetchMock.mock.calls.map(([, init]) => init.headers['Idempotency-Key'])
    expect(keys[0]).not.toBe(keys[1])
  })
})

describe('the API layer carries HTTP status on its errors', () => {
  beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_SIM', 'false') })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('so outcomeIsUncertain can tell a rejection from an unknown', async () => {
    // Without this the check reads `undefined` for every failure and answers "uncertain" to
    // everything — the safe direction, but not a check.
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 422, statusText: 'Unprocessable',
      json: async () => ({ detail: 'bad folder' }),
      headers: { get: () => null }, url: '',
    })))
    const { startScanQueued } = await import('./api.js')
    const { outcomeIsUncertain } = await import('./submitIntent.js')

    const err = await startScanQueued('local').catch((e) => e)
    expect(err.status).toBe(422)
    expect(outcomeIsUncertain(err.status)).toBe(false)
  })
})

describe('the submit path is wired to the intent', () => {
  it('App.jsx passes a retained key and only releases it on a known outcome', () => {
    const src = read('App.jsx')
    expect(src).toContain("beginOrResumeIntent('scan')")
    expect(src).toContain('startScanQueued(apiSource, folder, aiEnabled, deepScan, excludeRemediated, incremental, picked, excluded, submitKey)')
    expect(src).toContain("completeIntent('scan')")
    // The key must be dropped ONLY when the server proved nothing was created.
    expect(src).toContain("if (!outcomeIsUncertain(err?.status)) abandonIntent('scan')")
  })
})
