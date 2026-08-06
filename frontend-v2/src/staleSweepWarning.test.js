/**
 * A failed scheduled sweep must be visible on Monitor, not only in the container log.
 *
 * `core._do_scheduled_scan` saves nothing when it cannot reach its source and leaves the
 * previous scan standing — right about the data, silent about the UI. `last_at` is the last
 * SUCCESSFUL scan, so a sweep failing every five minutes never moves it and the schedule panel
 * reads as healthy while the estate ages. Live 2026-07-29: a Drive 403 insufficient-scopes loop
 * ran unnoticed for exactly this reason.
 *
 * /schedule now carries `last_sweep` ({ok, at, source, error, files, scan_id}) —
 * tests/test_sweep_failure_visible.py pins the server half.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
// Executable lines only: a comment describing the deleted bug is not the bug.
const code = (f) => readFileSync(join(here, f), 'utf8').split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') && !t.startsWith('{/*') })
  .join('\n')

const mon = code('Monitor.jsx')

describe('Monitor reads the sweep OUTCOME, not just the last success', () => {
  it('takes last_sweep off /schedule', () => {
    expect(mon).toMatch(/setLastSweep\(s\.last_sweep \|\| null\)/)
  })

  it('also keeps last_at, so the warning can date what is on screen', () => {
    // "The estate has not refreshed" is only actionable with the age of what IS showing.
    expect(mon).toMatch(/setSchedLastAt\(s\.last_at \|\| null\)/)
  })
})

describe('a failed sweep raises a stale-estate warning', () => {
  it('renders only for an explicit failure — not for "no sweep has run yet"', () => {
    // `lastSweep` is null before the first sweep and on any pre-upgrade deployment. A truthiness
    // test would warn about a sweep that never happened; `ok === false` is the real signal.
    expect(mon).toMatch(/lastSweep && lastSweep\.ok === false/)
    expect(mon).not.toMatch(/lastSweep && !lastSweep\.ok\b/)
  })

  it('says the estate is stale, which is the part a log line cannot say', () => {
    expect(mon).toMatch(/the estate below has not refreshed/)
    expect(mon).toMatch(/saved no scan/)
  })

  it('is announced, not just coloured', () => {
    expect(mon).toMatch(/role="alert"[\s\S]{0,400}the last scheduled sweep failed/i)
  })

  it('shows the underlying error so the cause is diagnosable from the UI', () => {
    expect(mon).toMatch(/\{lastSweep\.error\}/)
  })

  it('reports when the sweep failed AND how old the standing scan is', () => {
    expect(mon).toMatch(/lastSweep\.at/)
    expect(mon).toMatch(/schedLastAt/)
  })
})
