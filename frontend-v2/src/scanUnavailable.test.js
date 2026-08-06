/**
 * A 404 on the active scan must be visible, and must not be scored.
 *
 * Live 2026-07-29 (v2026.7.29.5): an allow-listed user's client held a scan id belonging to
 * another account. Scans are private to the user who ran them, so every per-scan read answered
 * 404. The client re-requested /traces and /diff for ~60s — every call ending in
 * `.catch(() => null)` — and Assess, on catching its own 404, computed a conformance result over
 * an empty file list and rendered a completed 0/100. The user saw no score and no error.
 *
 * These tests pin the two halves of the fix:
 *   1. api.js announces the 404 BEFORE throwing, so a caller's .catch cannot swallow it;
 *   2. nothing fabricates a score from a scan that could not be loaded.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
// api.js short-circuits to canned data whenever SIM is on, and SIM defaults ON under vitest
// (`import.meta.env.VITE_SIM !== 'false'`). These tests are about the REAL fetch path, so turn
// it off for this module only — setting it globally would reroute every other suite.
vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))

const { SCAN_UNAVAILABLE, getScan, getScanTraces, getScanPii, assessScan, setGoogleToken } =
  await import('./api.js')

const here = dirname(fileURLToPath(import.meta.url))
// Executable lines only: a comment describing the deleted bug is not the bug.
const code = (f) => readFileSync(join(here, f), 'utf8').split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') })
  .join('\n')

const BASE = 'http://localhost:8077'
const SID = 'a242d0f5f635'

/** A Response-alike carrying `url`, which is what api.js reads the scan id off. */
const notFound = (url, detail = 'scan not found') => ({
  ok: false, status: 404, statusText: 'Not Found', url,
  json: async () => ({ detail }),
})

let events
let listener
beforeEach(() => {
  setGoogleToken('token')          // real mode: the wrappers must hit fetch, not SIM
  events = []
  // Kept in a variable and REMOVED below. A listener left attached still closes over the
  // module-level `events` binding, so every past test's listener pushes into the current
  // test's array — 6 listeners, 6 copies of one event, and assertions that read like the
  // dispatch fired repeatedly.
  listener = (e) => events.push(e.detail)
  window.addEventListener('acp:scan-unavailable', listener)
})
afterEach(() => {
  window.removeEventListener('acp:scan-unavailable', listener)
  vi.unstubAllGlobals()
  events = []
})

describe('the message says what happened', () => {
  it('names the cause in the user’s terms and leaks no implementation', () => {
    expect(SCAN_UNAVAILABLE).toMatch(/isn’t available to your account/i)
    expect(SCAN_UNAVAILABLE).toMatch(/private to the person who ran them/i)
    expect(SCAN_UNAVAILABLE).not.toMatch(/404|owner_email|403|Bearer/i)
  })
})

describe('api.js announces an unloadable scan', () => {
  const cases = [
    ['getScan', () => getScan(SID), `${BASE}/scans/${SID}`],
    ['getScanTraces', () => getScanTraces(SID), `${BASE}/scans/${SID}/traces`],
    ['assessScan', () => assessScan(SID, 'AA'), `${BASE}/scans/${SID}/assess?level=AA`],
  ]

  cases.forEach(([name, call, url]) => {
    it(`${name} dispatches acp:scan-unavailable with the scan id, and rejects`, async () => {
      vi.stubGlobal('fetch', vi.fn(async () => notFound(url)))

      await expect(call()).rejects.toMatchObject({ scanUnavailable: true, scanId: SID })

      expect(events).toEqual([{ scanId: SID, reason: SCAN_UNAVAILABLE }])
    })
  })

  it('still announces when the CALLER swallows the error — the actual silent path', async () => {
    // getScanPii ends in `.catch(() => null)`. That is why the incident was invisible; dispatching
    // before the throw is what makes it visible anyway.
    vi.stubGlobal('fetch', vi.fn(async () => notFound(`${BASE}/scans/${SID}/pii`)))

    await expect(getScanPii(SID)).resolves.toBeNull()

    expect(events).toEqual([{ scanId: SID, reason: SCAN_UNAVAILABLE }])
  })

  it('does NOT fire for a 404 that is not a missing scan', async () => {
    // A per-file or per-trace 404 under a scan the user DOES own is a different problem, and
    // evicting their scan for it would be a regression of its own.
    vi.stubGlobal('fetch', vi.fn(async () => notFound(
      `${BASE}/scans/${SID}/trace/file/report.pdf`, 'trace not found')))

    await expect(getScan(SID)).rejects.toThrow(/trace not found/)

    expect(events).toEqual([])
  })

  it('does NOT fire for a 404 with no scan id in the URL', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => notFound(`${BASE}/rubric`, 'scan not found')))

    await expect(getScan(SID)).rejects.toBeTruthy()

    expect(events).toEqual([{ scanId: null, reason: SCAN_UNAVAILABLE }])
  })
})

describe('Assess never scores a scan it could not load', () => {
  const runner = code('AssessRunner.jsx')

  it('the assess catch returns instead of falling through to computeResult', () => {
    // The bug: `.catch(() => { ... const computed = computeResult(level) ... })` ran for EVERY
    // error, including the 404 — producing a completed verdict over zero documents.
    expect(runner).toMatch(/catch\(\(e\) => \{[\s\S]{0,400}e\?\.scanUnavailable[\s\S]{0,300}return\s*\n/)
    expect(runner).toMatch(/setScanGone\(e\.message\)/)
  })

  it('the deferred poll stops rather than retrying an id that will never resolve', () => {
    expect(runner).toMatch(/if \(e\?\.scanUnavailable\) \{[\s\S]{0,120}clearInterval\(timer\.current\)/)
  })

  it('and it is announced, not just logged', () => {
    expect(runner).toMatch(/role="alert"/)
    expect(runner).toMatch(/No score — this scan can’t be opened/)
    expect(runner).toMatch(/\{scanGone\}/)
  })

  it('a re-run clears the previous failure so it cannot outlive the problem', () => {
    expect(runner).toMatch(/setScanGone\(null\)/)
  })
})

describe('App recovers to a scan the user can actually load', () => {
  const app = code('App.jsx')

  it('listens for the event', () => {
    expect(app).toMatch(/addEventListener\('acp:scan-unavailable'/)
  })

  it('ignores a 404 for a scan other than the one on screen', () => {
    expect(app).toMatch(/if \(badId && current && badId !== current\) return/)
  })

  it('re-reads the owner-scoped list and opens a DIFFERENT scan', () => {
    // /scans is owner-scoped, so everything it returns is loadable — that is the invariant the
    // recovery leans on (tests/test_foreign_scan_404.py pins it server-side).
    expect(app).toMatch(/await listScans\(\)/)
    expect(app).toMatch(/list\.find\(\(s\) => s\.id !== badId\)/)
  })

  it('guards against the recovery itself 404ing', () => {
    expect(app).toMatch(/recoveringRef\.current\) return/)
  })

  it('clears the dead scan and routes to Discover when the user has none of their own', () => {
    expect(app).toMatch(/setScan\(null\); resetScanScopedState\(\)/)
    expect(app).toMatch(/'discover'/)
  })

  it('renders an alert rather than an empty dashboard', () => {
    expect(app).toMatch(/\{scanUnavailable && \(/)
    expect(app).toMatch(/role="alert"/)
  })

  it('a fresh sign-in clears it', () => {
    expect(app).toMatch(/setScanUnavailable\(null\)/)
  })
})
