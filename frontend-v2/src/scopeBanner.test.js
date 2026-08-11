import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Remediate and Publish showed finding counts, remediation progress and a certification decision
// with NO statement of what was assessed to produce them — zero references to activeScope in
// either file, while Discover, Assess, Overview and Transparency all name their scope.
//
// This is the defect class the codebase has fixed twice: a header reading "20 of 20 criteria
// automated" above six rows, and the dashboard totals in #77/#84. A number a reader cannot
// reconcile against what is in front of them costs more confidence than an unflattering one.
//
// Source-level, like the other v2 structure tests: this asserts that a component is PRESENT and
// placed ABOVE the numbers it qualifies. A mount-based test would need the whole run/files
// fixture stack, and one that rendered an empty screen would pass "the banner is not missing" by
// rendering nothing at all.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('ScopeBanner', () => {
  it('exists and names BOTH scopes', () => {
    // They answer different questions and either can silently shrink a total: which CRITERIA
    // were assessed (the operator's scan_scope, what the backend gated on) and which FILES were
    // scanned (a one-folder run vs the whole drive).
    const s = read('ScopeBanner.jsx')
    expect(s).toContain("from './activeScope.js'")
    expect(s).toContain("from './scanScope.js'")
    expect(s).toMatch(/SCOPE_SIZE/)
    expect(s).toMatch(/scopeSentence\(run\?\.scope/)
  })

  it('renders whether or not the scope is narrow', () => {
    // A caveat that appears only sometimes teaches a reader to read its absence as "everything",
    // which is exactly how the original folder-scan incident went unnoticed (scanScope.js).
    const s = read('ScopeBanner.jsx')
    expect(s).not.toMatch(/if \(!narrow\) return null/)
    expect(s).not.toMatch(/narrow \&\& \(/)
  })
})

describe('the screens that were missing it', () => {
  for (const file of ['Remediate.jsx', 'Publish.jsx']) {
    it(`${file} renders the banner`, () => {
      const s = read(file)
      expect(s).toContain("import ScopeBanner from './ScopeBanner.jsx'")
      expect(s).toMatch(/<ScopeBanner\b/)
    })

    it(`${file} places it ABOVE the numbers it qualifies`, () => {
      // Below the counts it is a footnote nobody reaches; the point is to be read first.
      //
      // Anchored to each screen's OWN first panel, not to the first `<section` in the file:
      // Remediate defines helper components (GroupedFixes) above its main render, and one of
      // them contains a panel — so a naive first-match compares against a section that is not on
      // the screen at all and reports a failure that is purely an artifact of file order.
      const anchor = { 'Remediate.jsx': 'rem-hero', 'Publish.jsx': 'Release Center' }[file]
      const s = read(file)
      const banner = s.indexOf('<ScopeBanner')
      const first = s.indexOf(anchor)
      expect(banner, 'no ScopeBanner rendered').toBeGreaterThan(-1)
      expect(first, `anchor ${anchor} not found`).toBeGreaterThan(-1)
      expect(banner, 'the banner renders after the content it qualifies').toBeLessThan(first)
    })
  }

  it('does not invent a findings count where none exists', () => {
    // Remediate has no open-findings total in scope. Passing a fabricated number to fill the
    // sentence would be precisely what this banner exists to prevent.
    const rem = read('Remediate.jsx')
    const call = rem.match(/<ScopeBanner[^>]*>/)[0]
    expect(call).not.toMatch(/findings=\{(?!0\})/)
  })

  it('is wired in the screens that already had scope, without duplicating it', () => {
    // Discover states its own scope inline and must not grow a second, differently-worded one.
    expect(read('Discover.jsx')).not.toContain('<ScopeBanner')
    expect(existsSync(join(HERE, 'ScopeBanner.jsx'))).toBe(true)
  })
})
