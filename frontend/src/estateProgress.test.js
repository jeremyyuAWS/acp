// Shared funnel-progress helper, used by both the Overview and Discover tabs so their funnels can
// never disagree about the same estate.
import { describe, it, expect } from 'vitest'
import { estateProgressFromFiles } from './estateProgress.js'
import { analysedCount } from './docStatus.js'

const FILES = [
  { type: 'docx', issues: [{ wcag: '2.4.2' }] },                                   // A: auto-fixable finding
  { type: 'docx', issues: [{ wcag: '9.9.9' }] },                                   // B: finding, no fix lane
  { type: 'docx', issues: [], remediated_at: '2026-08-19', published_at: '2026-08-19' }, // C: clean, remediated + published
  { type: 'docx', issues: [{ wcag: '2.4.2', severity: 'REVIEW' }] },               // D: fixable AND review-severity
]

describe('estateProgressFromFiles', () => {
  it('counts documents with any finding', () => {
    expect(estateProgressFromFiles(FILES).issues).toBe(3)   // A, B, D
  })

  it('remediation_eligible is finding-level (auto/AI-fixable only)', () => {
    expect(estateProgressFromFiles(FILES).remediation_eligible).toBe(2)   // A, D — not B (no lane), not C (no finding)
  })

  it('counts remediated documents (remediated_at or drive_write_url)', () => {
    expect(estateProgressFromFiles(FILES).remediated).toBe(1)             // C
    expect(estateProgressFromFiles([{ type: 'docx', drive_write_url: 'http://x' }]).remediated).toBe(1)
  })

  it('counts human-review documents (a REVIEW-severity finding)', () => {
    expect(estateProgressFromFiles(FILES).human_review).toBe(1)          // D
  })

  it('counts published documents', () => {
    expect(estateProgressFromFiles(FILES).published).toBe(1)             // C
  })

  it('delegates assessed to analysedCount', () => {
    expect(estateProgressFromFiles(FILES).assessed).toBe(analysedCount(FILES))
  })

  it('is safe on empty / missing input', () => {
    const z = estateProgressFromFiles(undefined)
    expect(z).toMatchObject({ issues: 0, remediation_eligible: 0, remediated: 0, human_review: 0, published: 0 })
  })
})
