import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('AssessRunner drives the real analysis when it is deferred (ADR 0020)', () => {
  it('branches on the deferred response and polls the real scan', () => {
    const s = read('AssessRunner.jsx')
    expect(s).toMatch(/\.then\(\(\) => assessScan\(runId, [^)]+\)\)\.then\(\(resp\)/)   // reads the response, not fire-and-forget
    expect(s).toMatch(/if \(resp && resp\.deferred\)/)          // deferred branch
    expect(s).toMatch(/const pollDeferred/)
    expect(s).toMatch(/getScan\(runId\)/)                        // polls the true per-file progress
    // finishes on the real completion signal, computing from freshly-scored files
    expect(s).toMatch(/run\.assessed_at \|\| run\.finalized_at/)
    expect(s).toMatch(/computeResultFrom\(scored, level\)/)
  })

  it('refreshes the scan Drive token before the deferred fan-out downloads (stale-token gap)', () => {
    const s = read('AssessRunner.jsx')
    expect(s).toMatch(/refreshScanDriveToken/)
    // the refresh runs BEFORE assessScan so the fan-out has a live token; best-effort for local
    expect(s).toMatch(/refreshScanDriveToken\(runId\)\)\.catch\(\(\) => \{\}\)\.then\(\(\) => assessScan\(runId, [^)]+\)\)/)
  })

  it('sends the pre-run screen\'s decision, not only its own local toggle', () => {
    const s = read('AssessRunner.jsx')
    // `opts` is AssessSetup's onRun descriptor. Falling back to local state when it is absent is
    // what keeps every pre-existing caller behaving exactly as before.
    expect(s).toMatch(/assessScan\(runId, opts\?\.level \|\| level, opts \? !!opts\.includeLifecycleFlagged : !ignoreLifecycle\)/)
    // The button must not hand React's MouseEvent in as the descriptor: an event is truthy, so
    // `opts.includeLifecycleFlagged` would read undefined and every click would silently send
    // include_lifecycle_flagged=false, ignoring the checkbox next to it.
    expect(s).not.toMatch(/onClick=\{assess\}/)
    expect(s).toMatch(/onClick=\{\(\) => assess\(\)\}/)
  })

  it('shows a "sign in again" path when a deferred assess opens nothing (session-expired)', () => {
    const s = read('AssessRunner.jsx')
    expect(s).toMatch(/accessFail = scored\.length === 0 && total > 0/)          // detect all-failed
    expect(s).toMatch(/sign-in has most likely expired/i)
    expect(s).toMatch(/if \(!accessFail\) onAssessed\?/)                        // don't announce a false 0% result
  })

  it('the immediate model is unchanged (optimistic reveal + cosmetic ticker)', () => {
    const s = read('AssessRunner.jsx')
    expect(s).toMatch(/onAssessed\?\.\(\)/)
    expect(s).toMatch(/runTicker\(startedAt, level, computed\)/)
  })

  it('counts DISCOVERED files as assessable, not excluded (the "Assess 0 files" regression)', () => {
    const s = read('AssessRunner.jsx')
    // discovered files (score null, status 'discovered') are assessable in the deferred model
    expect(s).toMatch(/status === 'discovered'/)
    expect(s).toMatch(/const assessmentFiles = files\.filter\(isAssessableFile\)/)
    expect(s).toMatch(/const assessN = deferredPending \? assessmentFiles\.length : docs\.length/)
    // the CTA + enablement use assessN, so the button isn't dead when nothing is scored yet
    expect(s).toMatch(/disabled=\{phase === 'running' \|\| !assessN \|\| scanBusy\}/)
    expect(s).toMatch(/▶ Assess \$\{assessN/)
    // the "excluded / could not be parsed" warning is suppressed pre-analysis
    expect(s).toMatch(/!deferredPending && excludedCount > 0/)
  })

  it('the AssessGate copy no longer claims the estate was already deep-scanned', () => {
    const app = read('App.jsx')
    // deferred means Discover did NOT open files — the gate must not imply a completed deep scan
    expect(app).not.toMatch(/discovered and deep-scanned/)
    expect(app).toMatch(/opens each file and scores it/)
  })
})
