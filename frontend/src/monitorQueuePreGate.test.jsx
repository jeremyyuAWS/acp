import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Live 2026-08-30: Discover's queued-scan card links "View in Monitor →" for exactly the moment
// a user wants to check queue/worker/Azure-capacity state — but Monitor's WHOLE content was
// nested inside `assessed ?`, so every click before assessment landed on a bare "Run the
// assessment to see results" screen instead. QueuePanel needs no assessment data at all (it's
// job-queue status, not a compliance view — Monitor.jsx mounts it standalone, no props), so it
// has no reason to be gated behind one.
//
// Source-level (matching remediateWiring.test.jsx's own established pattern for this exact
// tradeoff): mounting the real App.jsx means stubbing its entire dependency graph just to reach
// one ternary branch, for a check that a static read answers directly and more legibly.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

describe('QueuePanel is visible on Monitor before the scan is assessed', () => {
  const app = () => code('App.jsx')

  it('imports QueuePanel', () => {
    expect(app()).toMatch(/import QueuePanel from '\.\/QueuePanel\.jsx'/)
  })

  it('renders QueuePanel alongside assessGate in the not-yet-assessed branch of the monitor tab', () => {
    const m = app().match(/\{view === 'monitor' && \(run \? \(assessed \? <Monitor [^]*?\/> : (.*?)\) : /)
    expect(m, "the monitor tab's run-exists ternary wasn't found in the shape this test expects").toBeTruthy()
    expect(m[1]).toMatch(/<QueuePanel \/>/)
    expect(m[1]).toMatch(/assessGate/)
  })

  it('does not also render QueuePanel a second time once <Monitor> itself mounts (it already includes one)', () => {
    const m = app().match(/\{view === 'monitor' && \(run \? \((.*?)\) : /)
    expect(m).toBeTruthy()
    // The assessed branch is everything before " : <><QueuePanel" — i.e. the <Monitor ...> call
    // itself must not carry a QueuePanel in the same expression.
    const assessedBranch = m[1].split(' : <>')[0]
    expect(assessedBranch).toMatch(/<Monitor /)
    expect(assessedBranch).not.toMatch(/<QueuePanel/)
  })
})
