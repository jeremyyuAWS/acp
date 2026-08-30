/**
 * One idempotency key per submit intent, retained across retries (PRD §4.A).
 *
 * The server has honoured an Idempotency-Key on POST /scans for some time — enqueue_scan looks it
 * up owner-scoped and returns the ORIGINAL (scan_id, job_id) rather than inserting. Nothing in the
 * client ever sent one, so acceptance test 4 ("duplicate submissions produce one logical job")
 * could not pass no matter what the backend did.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  beginOrResumeIntent, completeIntent, abandonIntent, hasOpenIntent, outcomeIsUncertain,
} from './submitIntent.js'

beforeEach(() => {
  try { sessionStorage.clear() } catch { /* not available in this env */ }
  // Drop the module's in-memory fallback too, so tests cannot leak into each other.
  abandonIntent('scan'); abandonIntent('other')
})

describe('a submit intent', () => {
  it('mints a key and returns the SAME one until the intent resolves', () => {
    const first = beginOrResumeIntent('scan')
    expect(first).toBeTruthy()
    expect(beginOrResumeIntent('scan')).toBe(first)
    expect(beginOrResumeIntent('scan')).toBe(first)
  })

  it('mints a NEW key for the next intent once this one is accepted', () => {
    const first = beginOrResumeIntent('scan')
    completeIntent('scan')
    const second = beginOrResumeIntent('scan')
    expect(second).not.toBe(first)
  })

  it('keeps intents separate by scope', () => {
    expect(beginOrResumeIntent('scan')).not.toBe(beginOrResumeIntent('other'))
  })

  it('reports whether an intent is open', () => {
    expect(hasOpenIntent('scan')).toBe(false)
    beginOrResumeIntent('scan')
    expect(hasOpenIntent('scan')).toBe(true)
    completeIntent('scan')
    expect(hasOpenIntent('scan')).toBe(false)
  })

  it('survives a reload mid-submit', () => {
    // The window where a duplicate is most likely: the request is in flight, the tab reloads,
    // the user clicks again. A fresh module read must find the open intent.
    const key = beginOrResumeIntent('scan')
    expect(sessionStorage.getItem('acp.submitIntent.scan')).toBe(key)
  })

  it('does not break when sessionStorage throws', () => {
    // Safari private mode and "block site data" throw on read AND write. A submit path must not
    // fail because storage is unavailable.
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    const getSpy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    try {
      const key = beginOrResumeIntent('scan')
      expect(key).toBeTruthy()
      expect(beginOrResumeIntent('scan')).toBe(key)   // the in-memory fallback still holds it
    } finally {
      spy.mockRestore(); getSpy.mockRestore()
    }
  })
})

describe('outcomeIsUncertain — which failures keep their key', () => {
  it('treats a network error or timeout as uncertain', () => {
    expect(outcomeIsUncertain(undefined)).toBe(true)
    expect(outcomeIsUncertain(null)).toBe(true)
  })

  it('treats the pool-exhaustion 503 as uncertain', () => {
    // It carries a blanket "No changes were made", but that claim is only provable when the pool
    // failed on the request's FIRST database touch — api/app.py's own handler docstring says so.
    // Trusting it would risk a duplicate scan; holding the key costs nothing.
    expect(outcomeIsUncertain(503)).toBe(true)
    expect(outcomeIsUncertain(500)).toBe(true)
    expect(outcomeIsUncertain(504)).toBe(true)
  })

  it('treats a 4xx as certain — nothing was created', () => {
    // Holding the key here would make the user's NEXT, corrected submission resolve to nothing.
    expect(outcomeIsUncertain(400)).toBe(false)
    expect(outcomeIsUncertain(401)).toBe(false)
    expect(outcomeIsUncertain(404)).toBe(false)
    expect(outcomeIsUncertain(422)).toBe(false)
  })

  it('treats an unrecognised status as uncertain', () => {
    expect(outcomeIsUncertain(0)).toBe(true)
    expect(outcomeIsUncertain(200)).toBe(true)   // only reached on a thrown 2xx; stay safe
  })
})
