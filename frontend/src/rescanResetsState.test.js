// A new scan is a new run. Nothing from the last one carries into it — and the last one is not
// lost either.
//
// There were FOUR paths that put a different scan on screen, and each reset a different subset:
//
//   sign-in        decisions, triage, certifiedDocs, publishedFiles, assessPhase, justAssessed
//   time-travel    decisions, certifiedDocs                       (NOT triage)
//   a new scan     nothing                                        (relied on hydration)
//   reconnect      nothing
//
// The gap that showed: `publishedFiles` gates the Publish and Monitor steps of the progress rail
// (`publish: publishedFiles.length > 0`). Publish a document, re-scan, and the NEW scan opened
// with Publish and Monitor already ticked, on the strength of files published against the
// previous one. `triage` was the other: after #78 a single in-scope mark excludes every unmarked
// file from remediation, so carrying another scan's marks across a switch is misleading, not
// merely untidy.
//
// These are source-shape assertions rather than a mounted App: App.jsx owns ~40 pieces of state
// behind a sign-in wall and a live API, and the property under test is "all four call sites go
// through one reset", which is a claim about the code, not about a rendered pixel.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'App.jsx'), 'utf8')
const code = src.split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') && !t.startsWith('{/*') })
  .join('\n')

describe('one reset, used by every path that changes the active scan', () => {
  it('the reset exists and clears the four scan-scoped values', () => {
    const fn = code.match(/const resetScanScopedState = \(\) => \{[\s\S]*?\n  \}/)
    expect(fn, 'resetScanScopedState should be defined').toBeTruthy()
    const body = fn[0]
    for (const setter of ['setDecisions({})', 'setTriage({})', 'setCertifiedDocs([])', 'setPublishedFiles([])']) {
      expect(body, `reset should call ${setter}`).toContain(setter)
    }
  })

  it('all seven call sites use it', () => {
    // sign-in, time-travel (switchScan), a new scan (doScan), reconnect (reconnectScan), reconnect
    // to a pending default-path JOB after a reload (reconnectJob — added alongside reconnectScan
    // because the default path has no scan_runs row for getActiveScan to find until its crawl
    // finishes, so it needed its OWN reconnect path via sessionStorage's active_job_id), and the
    // two branches of the acp:scan-unavailable recovery (opening a different scan, and clearing
    // the dead one when the user has none of their own — both change the active scan, so both
    // must reset). The definition reads `const resetScanScopedState = () => {`, so it does not
    // match this pattern — every hit is a call. A path appearing WITHOUT one is the drift this
    // exists to stop; a new path appearing WITH one is the rule being followed, so bump the count
    // and name it here.
    const calls = code.match(/resetScanScopedState\(\)/g) || []
    expect(calls.length).toBe(7)
  })

  it('the scan-unavailable recovery resets too — it changes the active scan', () => {
    const handler = code.match(/const onUnavailable = async[\s\S]*?\n    \}\n/)
    expect(handler, 'the acp:scan-unavailable handler should be found').toBeTruthy()
    expect(handler[0]).toMatch(/setScan\(loaded\); resetScanScopedState\(\)/)
    expect(handler[0]).toMatch(/setScan\(null\); resetScanScopedState\(\)/)
  })

  it('a new scan resets, which is the case that never did', () => {
    const doScan = code.match(/const doScan = async[\s\S]*?\n  \}\n/)
    expect(doScan).toBeTruthy()
    // setScanUnavailable(null) landed between these two lines (a stale-banner fix, found live
    // 2026-08-21: a fresh successful scan never cleared an earlier failed reconnect's leftover
    // "scan not available" banner) — still immediately followed by the reset this test pins.
    expect(doScan[0]).toMatch(/setScan\(fresh\)\s*\n\s*setScanUnavailable\(null\)\s*\n\s*resetScanScopedState\(\)/)
  })

  it('time-travel resets, and no longer clears decisions while leaving triage behind', () => {
    const sw = code.match(/const switchScan = async[\s\S]*?\n  \}\n/)
    expect(sw).toBeTruthy()
    expect(sw[0]).toContain('resetScanScopedState()')
    // The old asymmetry: a bare setDecisions({}) with no matching setTriage({}).
    expect(sw[0]).not.toMatch(/setDecisions\(\{\}\)/)
  })

  it('reconnect resets too', () => {
    const rc = code.match(/const reconnectScan = async[\s\S]*?\n  \}\n/)
    expect(rc).toBeTruthy()
    expect(rc[0]).toContain('resetScanScopedState()')
  })

  it('reconnecting a pending default-path job resets too', () => {
    const rj = code.match(/const reconnectJob = async[\s\S]*?\n  \}\n/)
    expect(rj).toBeTruthy()
    expect(rj[0]).toContain('resetScanScopedState()')
  })
})

describe('what the reset deliberately leaves alone', () => {
  it('does not clear assessPhase or justAssessed — both self-correct', () => {
    // AssessRunner is keyed on run.id so it remounts per scan and re-emits onPhase from that
    // run's own saved state; justAssessed is compared by id, so a stale value cannot match.
    // Clearing them would flash the Overview's gated panels off and back on for no gain.
    const fn = code.match(/const resetScanScopedState = \(\) => \{[\s\S]*?\n  \}/)[0]
    expect(fn).not.toContain('setAssessPhase')
    expect(fn).not.toContain('setJustAssessed')
  })

  it('AssessRunner is still keyed on the run, which is what makes that safe', () => {
    expect(code).toMatch(/<AssessRunner key=\{run\.id\}/)
    expect(code).toMatch(/onPhase=\{setAssessPhase\}/)
  })

  it('justAssessed is still compared by id, not used as a boolean', () => {
    expect(code).toMatch(/justAssessed === run\?\.id/)
  })

  it('sign-in still resets them, because a new session has no assessment in flight', () => {
    const signIn = code.match(/const signIn = \(p\) => \{[\s\S]*?\n  \}\n/)
    expect(signIn[0]).toContain('resetScanScopedState()')
    expect(signIn[0]).toContain("setAssessPhase('idle')")
    expect(signIn[0]).toContain('setJustAssessed(null)')
  })
})

describe('the previous scan is preserved, not discarded', () => {
  it('decisions and triage are persisted per scan and re-fetched on every switch', () => {
    // This is what makes clearing safe: the reset drops the IN-MEMORY copy, and the hydration
    // effect refills it from the server for whichever scan is now active. A run abandoned
    // half-way keeps its own decisions and is still selectable in Time-travel.
    expect(code).toMatch(/getDecisions\(sid\)/)
    expect(code).toMatch(/saveDecisionsBatch\(sid, items\)/)
  })

  it('the persist effect refuses to write to a scan that is no longer active', () => {
    // Without this guard, clearing state on switch could persist the cleared values onto the
    // scan being left — turning a reset into data loss.
    expect(code).toMatch(/if \(!sid \|\| sid !== scan\?\.run\?\.id\) return/)
  })

  it('hydration writes are not echoed back to the server', () => {
    expect(code).toMatch(/if \(hydratingRef\.current\) \{ hydratingRef\.current = false; return \}/)
  })
})
