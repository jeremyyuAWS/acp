/**
 * `GET /scans/{sid}/events` — the live-run SSE stream — is DELIBERATELY not consumed.
 *
 * Written for the reason `discoverUploadRemoved.test.jsx` and `scopeStep.test.js` exist: an orphan
 * nobody writes down becomes a lie. That endpoint is live, owner-scoped and tested
 * (tests/test_live_events.py), so it reads as shipped live-streaming on every status list — and it
 * streams to nobody. Surfaced while researching ADR 0043; this is the decision it asked for.
 *
 * THE RUNNING SCREEN POLLS INSTEAD, and that is the intended state, not an oversight.
 * `LiveAssessmentLive` → `useLiveSnapshot` → `GET /scans/{sid}/live` every 2000 ms. Switching it to
 * the stream was considered and rejected on the evidence:
 *
 *   1. It would put MORE load on Postgres, not less. The stream's generator calls
 *      `live_snapshot.build_snapshot` — real DB work — every `_STREAM_INTERVAL_S` (1.0 s) per
 *      connected client, against the poll's 2.0 s. That is double the read rate per viewer, plus a
 *      held socket and coroutine each. In a repo where `core._maybe_checkpoint` was throttled to
 *      one write per 20 s after the 2026-08-26 Postgres connection exhaustion, doubling a
 *      per-client read rate is the wrong direction for a 1 s latency win.
 *   2. It cannot use the browser's `EventSource`. That API cannot send custom headers, and every
 *      call in api.js authenticates with a bearer token; putting the token in the URL would place
 *      it in proxy logs and browser history, which this app refuses (HIPAA/BAA). Wiring it means
 *      hand-rolling a second `fetch` + `ReadableStream` reader like `openDiscoverStream` — real new
 *      code in the area with four fixes behind it in two weeks.
 *   3. `_MAX_STREAM_ITERS` (1800 × 1 s = ~30 min) means a long assess run OUTLIVES its own stream,
 *      so the client would need reconnect logic the poll does not need — in that same area.
 *   4. Three properties `useLiveSnapshot` documents would each have to be rebuilt on the stream
 *      path: the `isNewerFrame` sequence guard, fail-soft retention of the last good snapshot
 *      through a transient error, and refocus-freshness on `visibilitychange`.
 *   5. ADR 0043 (ratified 2026-08-30) settles the general form of this: these are snapshot-REPLACE
 *      streams, so the first frame after any reconnect already IS the current state and streaming
 *      buys little over polling. Displacing a working, guarded poll with one would sit against the
 *      reasoning approved that day.
 *
 * The endpoint is NOT deleted, per CLAUDE.md's standing instruction to keep retired features in the
 * tree so restoring one is a single commit. If any of (1)–(5) stops holding — the interval is
 * reconciled, the auth-header problem is solved, or a genuinely event-sourced stream replaces the
 * snapshot one — wiring it becomes a live option again, and THIS TEST FAILING IS THE REMINDER TO
 * DELETE IT rather than a regression to fix.
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Comments stripped for the same reason discoverUploadRemoved.test.js strips them: the comment
// EXPLAINING an absence necessarily names the thing it is absent, so a whole-file ban would match
// its own protected explanation. That has failed on correct code four times in this repo.
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

const sources = () => readdirSync(here)
  .filter((f) => (f.endsWith('.js') || f.endsWith('.jsx')) && !f.includes('.test.'))

describe('the live-run SSE stream is deliberately unconsumed', () => {
  it('no module opens /scans/{id}/events', () => {
    const callers = sources().filter((f) => /\/events(`|'|"|\?)/.test(code(f)))
    expect(callers,
      'something now consumes the live-events stream — that is a real decision (see this file\'s '
      + 'header for what it costs); delete this test rather than un-wiring it').toEqual([])
  })

  it('and no EventSource is opened against it', () => {
    // Belt and braces: a consumer could be built without the literal path in the same file.
    const es = sources().filter((f) => /new EventSource\([^)]*events/.test(code(f)))
    expect(es).toEqual([])
  })

  it('the sweep is actually reading files — this cannot pass vacuously', () => {
    const all = sources()
    expect(all.length).toBeGreaterThan(100)
    // A control: the path the running screen DOES use is findable by the same matcher shape, so a
    // broken regex or an empty directory read would be caught here rather than reported as "clean".
    expect(sources().some((f) => /\/live/.test(code(f)))).toBe(true)
  })
})

describe('what the running screen uses instead', () => {
  it('LiveAssessmentLive polls the snapshot endpoint through useLiveSnapshot', () => {
    expect(existsSync(join(here, 'useLiveSnapshot.js'))).toBe(true)
    const l = code('LiveAssessmentLive.jsx')
    expect(l).toMatch(/useLiveSnapshot\(/)
    const h = code('useLiveSnapshot.js')
    expect(h).toMatch(/getScanLive\(/)
    expect(h).toMatch(/setInterval\(/)
  })

  it('and the poll keeps the three guarantees that make the stream not worth the swap', () => {
    // Named individually so that removing one is a visible change rather than a quiet regression
    // that also weakens the argument recorded above.
    const h = code('useLiveSnapshot.js')
    expect(h, 'sequence guard').toMatch(/isNewerFrame\(/)
    expect(h, 'fail-soft: a transient error keeps the last good snapshot').toMatch(/catch\s*\{/)
    expect(h, 'refocus-fresh').toMatch(/visibilitychange/)
  })
})
