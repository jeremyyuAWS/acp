import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('AssessRunner drives the real analysis when it is deferred (ADR 0020)', () => {
  it('branches on the deferred response and polls the real scan', () => {
    const s = read('AssessRunner.jsx')
    expect(s).toMatch(/assessScan\(runId, level\)\.then/)      // reads the response, not fire-and-forget
    expect(s).toMatch(/if \(resp && resp\.deferred\)/)          // deferred branch
    expect(s).toMatch(/const pollDeferred/)
    expect(s).toMatch(/getScan\(runId\)/)                        // polls the true per-file progress
    // finishes on the real completion signal, computing from freshly-scored files
    expect(s).toMatch(/run\.assessed_at \|\| run\.finalized_at/)
    expect(s).toMatch(/computeResultFrom\(scored, level\)/)
  })

  it('the immediate model is unchanged (optimistic reveal + cosmetic ticker)', () => {
    const s = read('AssessRunner.jsx')
    expect(s).toMatch(/onAssessed\?\.\(\)/)
    expect(s).toMatch(/runTicker\(startedAt, level, computed\)/)
  })

  it('the AssessGate copy no longer claims the estate was already deep-scanned', () => {
    const app = read('App.jsx')
    // deferred means Discover did NOT open files — the gate must not imply a completed deep scan
    expect(app).not.toMatch(/discovered and deep-scanned/)
    expect(app).toMatch(/opens each file and scores it/)
  })
})
