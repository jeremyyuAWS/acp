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

  it('passes the full funnel progress via the shared helper — every stage a real count, none guessed', () => {
    // The progress computation lives in estateProgress.js — shared with the Discover tab so the two
    // funnels can never disagree about the same estate. Overview computes it from the file rows there.
    expect(src).toMatch(/import \{ estateProgressFromFiles \} from '\.\/estateProgress\.js'/)
    expect(src).toMatch(/const estateProgress = estateProgressFromFiles\(files\)/)

    // The real-count definitions moved with it — assessed/issues/remediation_eligible/remediated +
    // human_review and published, each counted from file rows, none guessed.
    const prog = readFileSync(join(here, 'estateProgress.js'), 'utf8')
    expect(prog).toMatch(/assessed: analysedCount\(fs\)/)
    expect(prog).toMatch(/remediated: fs\.filter\(\(f\) => f\.remediated_at \|\| f\.drive_write_url\)\.length/)
    expect(prog).toMatch(/remediation_eligible: remediationEligibleCount\(fs\)/)
    expect(prog).toMatch(/published: fs\.filter\(\(f\) => f\.published_at\)\.length/)
    // human_review is derived, not guessed: REVIEW-severity findings per file.
    expect(prog).toMatch(/severity[\s\S]{0,40}REVIEW/)
  })
})
