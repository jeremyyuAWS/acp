import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// ADR 0026 Epic 1 — Coverage Manifest: every criterion row carries its evidence counts (real
// counts only) and the expanded issues render the detector's measured value from STRUCTURED
// evidence via the shared formatter — never parsed from prose, never estimated.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'FileDrawer.jsx'), 'utf8')

describe('Coverage Manifest — criterion resolved, with the evidence counts that back it', () => {
  it('row counts come from real data: review flags, pending queue items, verified fixes', () => {
    expect(src).toMatch(/reviewCount: reviewIssues\.length/)
    expect(src).toMatch(/pending: hitlBySc\[c\.sc\] \|\| 0/)
    expect(src).toMatch(/verifiedFixed: remediatedRuleIds\.has\(c\.sc\)/)
    expect(src).toMatch(/hitlBySc\[hsc\] = \(hitlBySc\[hsc\] \|\| 0\) \+ \(h\.finding_count \|\| 1\)/)
  })

  it('the evidence line renders only when a real count exists — a clean row shows nothing', () => {
    expect(src).toMatch(/r\.count > 0 \|\| r\.reviewCount > 0 \|\| r\.pending > 0 \|\| r\.verifiedFixed/)
  })

  it('the inline measured value comes only from structured evidence, via the shared formatter', () => {
    expect(src).toMatch(/issue\.evidence && issue\.evidence\.value != null/)
    expect(src).toMatch(/fmtEvidence\(issue\.evidence\.value, issue\.evidence\.unit\)/)
    // one formatter shared with EvidenceHeader — the two surfaces can never disagree
    expect(src).toMatch(/import EvidenceHeader, \{ fmtEvidence \} from '\.\/EvidenceHeader\.jsx'/)
  })
})

describe('Confirm-the-pass — the honest way a 🟡 turns green (recorded, never waved through)', () => {
  it('the affordance exists only on REVIEW rows and records via confirmCriterion', () => {
    expect(src).toMatch(/r\.outcome === 'REVIEW' && scanId && \(confirmedScs\.has\(r\.id\)/)
    expect(src).toMatch(/confirmCriterion\(scanId, file\.file, r\.id\)/)
    expect(src).toMatch(/if \(res\?\.ok\) setConfirmedScs/)   // flips only on a server-acknowledged write
  })
})
