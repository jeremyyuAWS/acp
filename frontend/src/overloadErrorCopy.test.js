/**
 * A user must not be shown "database_busy".
 *
 * The overload 503 carries a written explanation — that is the whole reason the backend composes
 * one — but api.js's error handler preferred `detail`, the machine tag, so the sentence was
 * discarded and the literal string "database_busy" reached the screen. #1045's own handler
 * docstring anticipated "a separate frontend fix (tracked, not yet built)" for exactly this.
 *
 * The machine-readable fields are kept ON the error rather than encoded into its text, so a
 * caller branches on `code`/`changes` instead of matching prose.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const overload = (extra = {}) => ({
  ok: false, status: 503, statusText: 'Service Unavailable', url: '',
  headers: { get: () => null },
  json: async () => ({
    detail: 'database_busy',
    code: 'DB_CAPACITY_BUSY',
    message: "ACP's database was temporarily at capacity. We could not confirm whether your request completed — check its status before submitting it again.",
    changes: 'unknown',
    request_id: 'req-abc123',
    occurred_at: '2026-08-30T16:41:03+00:00',
    ...extra,
  }),
})

describe('the overload 503 reaching a user', () => {
  beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_SIM', 'false') })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('shows the written sentence, not the machine tag', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => overload()))
    const { startScanQueued } = await import('./api.js')
    const err = await startScanQueued('local').catch((e) => e)

    expect(err.message).not.toBe('database_busy')
    expect(err.message).toContain('temporarily at capacity')
    expect(err.message).toContain('could not confirm')
  })

  it('keeps the machine-readable fields on the error for branching', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => overload()))
    const { startScanQueued } = await import('./api.js')
    const err = await startScanQueued('local').catch((e) => e)

    expect(err.status).toBe(503)
    expect(err.code).toBe('DB_CAPACITY_BUSY')
    expect(err.detail).toBe('database_busy')
    expect(err.changes).toBe('unknown')
    expect(err.requestId).toBe('req-abc123')
    expect(err.occurredAt).toBe('2026-08-30T16:41:03+00:00')
  })

  it('an uncertain overload keeps the submit intent open, so a retry cannot duplicate', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => overload()))
    const { startScanQueued } = await import('./api.js')
    const { beginOrResumeIntent, outcomeIsUncertain, hasOpenIntent } = await import('./submitIntent.js')
    try { sessionStorage.clear() } catch { /* unavailable */ }

    const key = beginOrResumeIntent('scan')
    const err = await startScanQueued('local', null, true, false, false, true, null, null, key)
      .catch((e) => e)

    expect(outcomeIsUncertain(err.status)).toBe(true)
    expect(hasOpenIntent('scan')).toBe(true)
    expect(beginOrResumeIntent('scan')).toBe(key)
  })

  it('still falls back to detail for endpoints that send no message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 404, statusText: 'Not Found', url: '',
      headers: { get: () => null },
      // Deliberately NOT "scan not found": that exact detail has its own handling in api.js
      // (the acp:scan-unavailable path), which would make this assert the wrong branch.
      json: async () => ({ detail: 'folder is no longer shared with you' }),
    })))
    const { startScanQueued } = await import('./api.js')
    const err = await startScanQueued('local').catch((e) => e)
    expect(err.message).toBe('folder is no longer shared with you')
  })
})
