import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import { eligibleShare } from './DiscoveryResults.jsx'

// ONE estate partition on the tab that partitions the estate.
//
// Discover rendered two, back to back: EstateCoverage (a funnel — discovered → assessable →
// remediable, plus format composition and a capability-status split) and DiscoveryResults (five
// buckets, a type breakdown, the unreadable reasons and the recommendations). Both answered "what
// is in this estate", with the same headline count and the same eligibility number derived twice.
//
// The funnel came off, for a reason Discover.jsx had ALREADY written down about itself a few
// hundred lines lower:
//
//     Discovery facts only. Rubric scores and remediation state used to appear here, which read as
//     "the scan already assessed and remediated your documents" — it does neither.
//
// A funnel whose third stage is REMEDIABLE is that same claim in chart form. It is not a retirement:
// EstateCoverage still mounts on Overview, where a cross-stage view belongs, so the capability is
// untouched and only the second copy on this one tab is gone.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

const { default: DiscoveryResults } = await import('./DiscoveryResults.jsx')

describe('Discover partitions the estate exactly once', () => {
  it('does not mount the coverage funnel', () => {
    const d = code('Discover.jsx')
    expect(d).not.toMatch(/<EstateCoverage\b/)
    expect(d).not.toMatch(/import EstateCoverage from/)
    // The stripper must not be what makes this pass.
    expect(d).toContain('export default function Discover')
    expect(d.length).toBeGreaterThan(2000)
  })

  it('and drops the progress derivation that fed it', () => {
    // estateProgressFromFiles reached nothing once the funnel went. A helper imported for a mount
    // that no longer exists is the leftover that makes the next reader think it is still in play.
    expect(code('Discover.jsx')).not.toMatch(/estateProgressFromFiles/)
  })

  it('but still renders the discovery partition', () => {
    expect(code('Discover.jsx')).toMatch(/<DiscoveryResults\b/)
  })

  it('EstateCoverage is now fully retired — Overview no longer mounts it either', () => {
    // The 2026-09-02 PRD simplification also removed EstateCoverage from Overview. The file is
    // kept for potential restoration; it is tracked as a deliberate orphan in
    // unmountedComponents.test.jsx.
    expect(existsSync(join(here, 'EstateCoverage.jsx'))).toBe(true)
    expect(code('Overview.jsx')).not.toMatch(/<EstateCoverage\b/)
  })
})

describe('the eligible share, which the funnel used to carry', () => {
  it('states a normal share as a rounded percentage', () => {
    expect(eligibleShare(3400, 12408)).toBe('27% of the estate')
  })

  it('says <1% rather than 0% for a small non-zero count', () => {
    // 22 of 12,408 is 0.18%. "0% of the estate" printed beneath a tile reading "22" asserts the
    // estate holds none of what that tile just counted — a rounding artefact that contradicts the
    // number it annotates, on exactly the estate shape this KPI exists for.
    expect(eligibleShare(22, 12408)).toBe('<1% of the estate')
  })

  it('says 0% only when the count really is zero', () => {
    expect(eligibleShare(0, 12408)).toBe('0% of the estate')
  })

  it('says nothing when it cannot be computed', () => {
    // No denominator, no share. A percentage of an unknown total is not a smaller claim than a
    // wrong one — it is the same claim with the boundary hidden.
    expect(eligibleShare(22, 0)).toBe(null)
    expect(eligibleShare(null, 12408)).toBe(null)
    expect(eligibleShare(22, null)).toBe(null)
    expect(eligibleShare(undefined, undefined)).toBe(null)
  })

  it('refuses a numerator bigger than its denominator', () => {
    // THE BUG THIS FIXTURE FOUND, on the first run. The tile's count is an ESTATE figure (from
    // scope.inventory) while summary.discovered counts the ROWS ON SCREEN, which a filter narrows.
    // Wired to the wrong one, 22 eligible over 12 rows rendered "183% of the estate" — a true
    // numerator over a denominator from another population. Nothing about reading the diff would
    // have shown it.
    expect(eligibleShare(22, 12)).toBe(null)
  })
})

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(DiscoveryResults, props)) })
  return container.textContent
}
afterEach(() => unmountAll())

describe('the share reaches the tile', () => {
  const files = Array.from({ length: 12 }, (_, i) => ({ file: `f${i}.docx`, name: `f${i}.docx`, status: 'done' }))

  it('renders under the count it qualifies, over the ESTATE listing', async () => {
    // 12 rows on screen, 12,408 in the estate, 22 eligible. The share must read against 12,408.
    const t = await mount({ files, inventory: { discovered: 12408, assessment_eligible: 22 } })
    expect(t).toMatch(/22\s*can be assessed\s*<1% of the estate/i)
    // And never against the row count — 22/12 is 183%, which is what this originally printed.
    expect(t).not.toMatch(/1?\d\d% of the estate/)
  })

  it('renders no share when nothing measured eligibility', async () => {
    // The tile itself is absent in that case, so the share must be too — a stray "0% of the
    // estate" with no tile above it would be a claim about an estate nobody partitioned.
    const t = await mount({ files, inventory: { discovered: 12408 } })
    expect(t).not.toMatch(/can be assessed/i)
    expect(t).not.toMatch(/of the estate/i)
  })
})
