import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// EstateCoverage was removed from Overview on 2026-09-02 (PRD "ACP Discover and Overview
// Simplification"). EstateProgressPanel and the compliance funnel cover the estate story;
// the three-denominator coverage view was redundant. This test pins the removal so the
// component cannot silently re-enter without failing here first.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Overview.jsx'), 'utf8')

describe('EstateCoverage is intentionally NOT rendered by Overview', () => {
  it('does not import EstateCoverage', () => {
    expect(src).not.toMatch(/import EstateCoverage from/)
  })

  it('does not render <EstateCoverage', () => {
    expect(src).not.toMatch(/<EstateCoverage[\s/>]/)
  })

  it('estateProgress.js still computes real counts — the helper is still valid for Discover', () => {
    const prog = readFileSync(join(here, 'estateProgress.js'), 'utf8')
    expect(prog).toMatch(/assessed: analysedCount\(fs\)/)
    expect(prog).toMatch(/remediated: fs\.filter\(\(f\) => f\.remediated_at \|\| f\.drive_write_url\)\.length/)
    expect(prog).toMatch(/remediation_eligible: remediationEligibleCount\(fs\)/)
    expect(prog).toMatch(/published: fs\.filter\(\(f\) => f\.published_at\)\.length/)
  })
})
