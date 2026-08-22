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
  it('Publish.jsx renders the banner', () => {
    const s = read('Publish.jsx')
    expect(s).toContain("import ScopeBanner from './ScopeBanner.jsx'")
    expect(s).toMatch(/<ScopeBanner\b/)
  })

  it('Publish.jsx places it ABOVE the numbers it qualifies', () => {
    const s = read('Publish.jsx')
    const banner = s.indexOf('<ScopeBanner')
    const first = s.indexOf('Release Center')
    expect(banner, 'no ScopeBanner rendered').toBeGreaterThan(-1)
    expect(first, 'anchor Release Center not found').toBeGreaterThan(-1)
    expect(banner, 'the banner renders after the content it qualifies').toBeLessThan(first)
  })

  it('Remediate.jsx renders AssessmentScopeCard above the numbers it qualifies', () => {
    // ScopeBanner was replaced by AssessmentScopeCard so the compact scope record is shared
    // with the Overview tab. The invariant — scope shown above the numbers — is still met.
    const s = read('Remediate.jsx')
    expect(s).toContain("import AssessmentScopeCard from './AssessmentScopeCard.jsx'")
    expect(s).toMatch(/<AssessmentScopeCard\b/)
    const card = s.indexOf('<AssessmentScopeCard')
    const hero = s.indexOf('rem-hero')
    expect(card, 'no AssessmentScopeCard rendered').toBeGreaterThan(-1)
    expect(hero, 'anchor rem-hero not found').toBeGreaterThan(-1)
    expect(card, 'the scope card renders after the content it qualifies').toBeLessThan(hero)
  })

  it('Remediate.jsx does not pass a fabricated findings count to the scope card', () => {
    // AssessmentScopeCard replaced ScopeBanner — it takes no findings prop. A fabricated count
    // would be exactly what the scope summary exists to prevent.
    const rem = read('Remediate.jsx')
    const call = rem.match(/<AssessmentScopeCard[^>]*\/>/)?.[0] || ''
    expect(call).not.toMatch(/findings=/)
  })

  it('is wired in the screens that already had scope, without duplicating it', () => {
    // Discover states its own scope inline and must not grow a second, differently-worded one.
    expect(read('Discover.jsx')).not.toContain('<ScopeBanner')
    expect(existsSync(join(HERE, 'ScopeBanner.jsx'))).toBe(true)
  })
})
