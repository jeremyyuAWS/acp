import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The estate dashboard (Overview) renders the three-denominator coverage view (EstateCoverage) from
// the scan's real scope.inventory. Source-level, matching the repo's other Overview wiring pins:
// a mount would need the whole run/files/props stack, and one that silently rendered an empty
// Overview would pass "there is a coverage section" by rendering nothing.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Overview.jsx'), 'utf8')

describe('Overview wires in EstateCoverage', () => {
  it('imports and renders EstateCoverage from the scan report', () => {
    expect(src).toMatch(/import EstateCoverage from '\.\/EstateCoverage\.jsx'/)
    expect(src).toMatch(/<EstateCoverage report=\{run\} progress=\{estateProgress\}/)
  })

  it('only shows it once discovery has inventoried the estate', () => {
    // Guarded on run.scope.inventory.discovered so it never renders an empty coverage section.
    expect(src).toMatch(/run\.scope\?\.inventory\?\.discovered > 0 &&/)
  })

  it('passes only cleanly-derivable funnel progress; the rest stay pending', () => {
    // assessed/issues/remediation_eligible/remediated come from real file rows; human-review and
    // published are deliberately absent (pending) rather than guessed.
    expect(src).toMatch(/assessed: analysed/)
    expect(src).toMatch(/remediated: files\.filter\(\(f\) => f\.remediated_at \|\| f\.drive_write_url\)\.length/)
    expect(src).not.toMatch(/estateProgress[\s\S]{0,200}published:/)
  })
})
