import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { outcomeIsUncertain } from './submitIntent.js'
import { SCAN_ENQUEUE_TIMEOUT_MS, BOOT_TIMEOUT_MS } from './api.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Production, 2026-09-01: a Discovery was submitted DURING a deployment, while the new API
// replicas were starting. The request never reached a server — no POST /discovery/preflight, no
// POST /scans, no scan id, no job id — and `startScanQueued` had no timeout, so it never settled.
// The browser sat in its optimistic "Submitting Discovery" state permanently, with no console
// error and nothing to retry. Workers were healthy the whole time; there was simply no job.
//
// The three properties that keep that from recurring are pinned here, because two of them are a
// single argument each that a refactor could drop with everything else still green.

describe('the scan enqueue is bounded', () => {
  it('startScanQueued passes an abort signal, so a stranded connection cannot hang forever', () => {
    const api = read('api.js')
    const call = /export const startScanQueued[\s\S]*?\n(?=export |\/\/ )/.exec(api)
    expect(call, 'startScanQueued not found').toBeTruthy()
    expect(call[0]).toMatch(/signal:\s*AbortSignal\.timeout\(SCAN_ENQUEUE_TIMEOUT_MS\)/)
  })

  it('is bounded far more loosely than a boot read — it is a write, not a page load', () => {
    // A ceiling tight enough to abort a request the server is really processing would be a worse
    // bug than the hang. This asserts the RELATIONSHIP, so tuning either value keeps it honest.
    expect(SCAN_ENQUEUE_TIMEOUT_MS).toBeGreaterThan(BOOT_TIMEOUT_MS)
    expect(SCAN_ENQUEUE_TIMEOUT_MS).toBeGreaterThanOrEqual(20000)
    expect(SCAN_ENQUEUE_TIMEOUT_MS).toBeLessThanOrEqual(60000)
  })
})

describe('a timed-out submit keeps its idempotency key', () => {
  // THE load-bearing property, and the reason bounding a WRITE is safe at all. A timeout says the
  // response was lost, NOT that the work was not done: the scan may exist. Abandoning the key
  // would mint a fresh one on retry, and the retry would enqueue a SECOND scan.
  it('an AbortSignal timeout is classified as uncertain', () => {
    const e = new Error('signal timed out'); e.name = 'TimeoutError'
    expect(e.status).toBeUndefined()              // nothing attaches a status before fetch resolves
    expect(outcomeIsUncertain(e.status)).toBe(true)
  })

  it('so does a dropped connection, which is what actually happened', () => {
    expect(outcomeIsUncertain(new TypeError('Failed to fetch').status)).toBe(true)
  })

  it('but a 4xx still drops the key — that request provably created nothing', () => {
    expect(outcomeIsUncertain(422)).toBe(false)
  })

  it('App holds the key on an uncertain enqueue failure and drops it only on a proven rejection', () => {
    const app = read('App.jsx')
    expect(app).toMatch(/if \(!outcomeIsUncertain\(err\?\.status\)\) abandonIntent\('scan'\)/)
  })
})

describe('an unconfirmed submit is reported as unconfirmed, not as a failure', () => {
  const app = read('App.jsx')

  it('records the uncertainty instead of only throwing', () => {
    expect(app).toMatch(/else setSubmitUncertain\(\{ source, folder, runScope, timedOut:/)
  })

  it('does NOT also claim "scan failed" for it — the two would contradict each other', () => {
    expect(app).toMatch(/if \(!outcomeIsUncertain\(e\?\.status\)\) setErr\(`scan failed:/)
  })

  it('says the scan may exist, and that retrying is safe rather than duplicating', () => {
    expect(app).toMatch(/It may or may not have started/)
    expect(app).toMatch(/reconciles to the same scan rather than starting a second one/)
  })

  it('offers a retry that re-runs the SAME attempt, so the held key is reused', () => {
    // Passing the original source/folder/runScope back into doScan is what makes
    // beginOrResumeIntent resume the held key instead of minting a new one.
    expect(app).toMatch(/doScan\(a\.source, a\.folder, a\.runScope\)/)
  })

  it('is a status, not an alert — the red treatment would push the user to scan again by hand', () => {
    const panel = /\{submitUncertain && \([\s\S]*?\n      \)\}/.exec(app)
    expect(panel, 'unconfirmed-submit panel not found').toBeTruthy()
    expect(panel[0]).toMatch(/role="status"/)
    expect(panel[0]).not.toMatch(/role="alert"/)
  })

  it('a fresh attempt clears the previous one’s notice', () => {
    expect(app).toMatch(/setBusy\(true\); setErr\(null\); setSubmitUncertain\(null\)/)
  })
})
