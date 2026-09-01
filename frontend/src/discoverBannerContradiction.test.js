// A failed scan attempt must not leave a stale capacity notice on screen underneath the failure
// banner. `preflightCapacityState` is set from the preflight probe BEFORE the actual enqueue call
// (App.jsx's doScan, ~line 1011: `if (capacityState && capacityState !== 'ready')
// setPreflightCapacityState(capacityState)`), and 'starting'/'busy' are non-blocking verdicts —
// the scan is allowed to proceed. If the subsequent startScanQueued() call then reports no workers
// available, doScan throws and the catch block sets `err` — but until this fix, nothing ever
// cleared `preflightCapacityState`, so Discover.jsx kept rendering "Preparing Discovery capacity —
// you can scan now" (Discover.jsx's capacity-notice block, gated on !busy) directly underneath
// App.jsx's "scan failed: no workers available" banner (the `.err` div). The two contradict each
// other: one says the scan just failed for lack of workers, the other says a worker is starting
// and you can scan now. Found live 2026-08-28.
//
// Source-shape assertion, same reasoning as rescanResetsState.test.js: App.jsx owns ~40 pieces of
// state behind a sign-in wall and a live API, so the property under test ("the failure catch
// clears the stale capacity state") is a claim about the code, not about a rendered pixel.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'App.jsx'), 'utf8')
const code = src.split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') && !t.startsWith('{/*') })
  .join('\n')

describe('a failed scan clears the stale preflight capacity notice', () => {
  it('doScan sets preflightCapacityState from the preflight probe', () => {
    const doScan = code.match(/const doScan = async[\s\S]*?\n  \}\n/)
    expect(doScan, 'doScan should be defined').toBeTruthy()
    expect(doScan[0]).toMatch(/setPreflightCapacityState\(capacityState\)/)
  })

  it("doScan's catch block clears preflightCapacityState before setting err", () => {
    const doScan = code.match(/const doScan = async[\s\S]*?\n  \}\n/)
    expect(doScan).toBeTruthy()
    // The catch that sets the "scan failed: ..." err message must also null out
    // preflightCapacityState — order matters only in that both must be in the same catch, not
    // split across catch/finally where a race could leave one stale.
    //
    // Asserted as "in the same catch, capacity cleared first" rather than as two adjacent lines.
    // Since 2026-09-01 the err set is GUARDED: a submit whose response was lost has its own,
    // more accurate surface ("the server did not confirm your scan"), and a red "scan failed"
    // beside it would be a third contradicting banner — the very thing this file exists to stop.
    // Pinning adjacency would have made that fix look like a regression.
    const c = /catch \(e\) \{[\s\S]*?\n    \} finally \{/.exec(doScan[0])
    expect(c, "doScan's catch block not found").toBeTruthy()
    const iCapacity = c[0].indexOf('setPreflightCapacityState(null)')
    const iErr = c[0].indexOf('setErr(`scan failed: ${scanFailureDetail(e?.message ?? e)}`)')
    expect(iCapacity, 'capacity notice not cleared in the catch').toBeGreaterThan(-1)
    expect(iErr, 'the "scan failed" message is not set in the catch').toBeGreaterThan(-1)
    expect(iCapacity).toBeLessThan(iErr)
  })

  it('preflightCapacityState is reset at the start of a new attempt too — belt and suspenders', () => {
    const doScan = code.match(/const doScan = async[\s\S]*?\n  \}\n/)
    // setSubmitUncertain(null) joined this line on 2026-09-01 (the unconfirmed-submit notice is
    // per-attempt too), so the two calls this test is about are no longer adjacent. Both still
    // have to be on the opening line of a fresh attempt, which is what is asserted.
    const open = /setBusy\(true\);[^\n]*\n/.exec(doScan[0])
    expect(open, 'doScan opening line not found').toBeTruthy()
    expect(open[0]).toMatch(/setErr\(null\)/)
    expect(open[0]).toMatch(/setPreflightCapacityState\(null\)/)
  })

  it('reconnectJob\'s catch does NOT touch preflightCapacityState — it never sets it, so nothing to clear', () => {
    // reconnectJob has its own "scan failed: ..." catch (page-reload reconnect to the default,
    // non-queued path) but never calls the preflight endpoint at all, so there is no stale
    // capacity state for it to leave behind. This test pins that the two catch sites stay
    // distinguishable rather than accidentally merging into one shared helper that over-clears.
    const reconnectJob = code.match(/const reconnectJob = async[\s\S]*?\n  \}\n/)
    expect(reconnectJob).toBeTruthy()
    expect(reconnectJob[0]).not.toContain('setPreflightCapacityState')
  })
})
