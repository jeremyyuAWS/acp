import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The pre-discovery scope grid offered all 29 criteria the engine can reach a verdict on. Twelve
// of those are criteria Mova iO does not track — 1.4.2, 1.4.4, 1.4.6, 1.4.8, 1.4.9, 1.4.10,
// 1.4.12, 2.4.1, 2.4.9, 2.4.10, 3.1.5, 3.3.2 — AAA rules and viewer behaviours. Each was a row an
// operator had to read and dismiss before reaching a decision they could act on, on the screen
// that is meant to be the FIRST thing they do.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

const tracked = () => {
  const m = read('ruleDetails.js').match(/TRACKED_17 = new Set\(\[(.*?)\]\)/s)
  return (m[1].match(/"[\d.]+"/g) || []).map((x) => x.replace(/"/g, ''))
}
const universe = () => {
  const s = read('scopePresets.js')
  return [...s.matchAll(/\{ sc: "([\d.]+)"/g)].map((m) => m[1])
}

describe('the grid offers the tracked criteria only', () => {
  it('filters the universe rather than listing criteria by hand', () => {
    // Filtering keeps the pairs coming from the generated, CI-guarded universe, so this can only
    // NARROW — it cannot offer a checkbox the engine has no verdict for. A hand-written list
    // could drift into offering one.
    const s = read('ScanScope.jsx')
    expect(s).toMatch(/const OFFERED = SCOPE_UNIVERSE\.filter\(\(r\) => TRACKED_17\.has\(r\.sc\)\)/)
    expect(s).toContain("import { TRACKED_17 } from './ruleDetails.js'")
  })

  it('renders and counts OFFERED, not the whole universe', () => {
    // The count has to move with the rows. A total over 29 above a grid of 17 is the same
    // unreconcilable-number defect this codebase has fixed three times.
    const s = read('ScanScope.jsx')
    expect(s).toMatch(/\{OFFERED\.map\(\(row\) => \(/)
    expect(s).toMatch(/const total = OFFERED\.reduce/)
    expect(s).not.toMatch(/\{SCOPE_UNIVERSE\.map/)
    expect(s).not.toMatch(/const total = SCOPE_UNIVERSE\.reduce/)
  })

  it('drops no tracked criterion — every one is in the universe', () => {
    // If a tracked criterion were absent from the universe the filter would silently hide it,
    // and an operator could not scope a rule the product says it follows. Derived on both sides
    // so it stays true as either list changes.
    const missing = tracked().filter((t) => !universe().includes(t))
    expect(missing, `tracked but not offerable: ${missing.join(', ')}`).toHaveLength(0)
  })

  it('actually removes the untracked ones', () => {
    const u = universe()
    const t = tracked()
    const extra = u.filter((sc) => !t.includes(sc))
    expect(extra.length, 'nothing to filter — the universe is already the tracked list').toBeGreaterThan(0)
    expect(t).toHaveLength(17)
  })
})

describe('a saved scope wider than the grid is preserved and declared', () => {
  it('keeps criteria the grid no longer shows', () => {
    // toPayload serialises everything in `sel`, so a scope set before this narrowing — or
    // written straight to the setting through the API — survives a save rather than being
    // silently trimmed to what happens to be on screen.
    const s = read('ScanScope.jsx')
    expect(s).toMatch(/for \(const \[sc, fmts\] of Object\.entries\(sel\)\) if \(fmts\.size\)/)
  })

  it('says how many are outside the tracked list', () => {
    // They are counted by `chosen` while no row shows them. Stating it is the difference between
    // a number that reconciles and one that quietly does not.
    const s = read('ScanScope.jsx')
    expect(s).toMatch(/const hidden = Object\.entries\(sel\)/)
    expect(s).toMatch(/outside the tracked list/)
    expect(s).toMatch(/Not shown: \$\{hidden\.join\(', '\)\}/)
  })
})
