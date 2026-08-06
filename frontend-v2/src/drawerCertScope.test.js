import { describe, it, expect, vi } from 'vitest'
import { SCOPE_SCS, OUT_OF_SCOPE_SCS } from './activeScope.js'
import { CAPABILITY_FALLBACK } from './capability.js'

// `computeCoverageRows` decides the rows of a document's CERTIFICATION RECORD — the PDF/HTML
// evidence a customer retains for ADA / EAA audits, which reportModel.js renders as
// "N of <rows.length> in-scope criteria pass".
//
// It was the widest list in the product: every document-applicable criterion at or below the
// conformance target — 42 at AA — while the on-screen coverage manifest it is supposed to mirror
// showed 20. So the certificate asserted conformance over a denominator that appeared nowhere on
// screen, and "in-scope" meant two different things one click apart. Both now resolve to the
// engagement's agreed scope.
//
// Tested here rather than through a mounted FileDrawer because the function is pure, and because
// what needs pinning is the row SET — a render test would prove the table shows what it was
// handed, not that the right thing was handed to it.

vi.mock('./api.js', () => ({
  getFileStatus: vi.fn(() => Promise.resolve(null)),
  getScanStatus: vi.fn(() => Promise.resolve(null)),
  explainFinding: vi.fn(), getFileContent: vi.fn(), uploadToDrive: vi.fn(),
  markRemediated: vi.fn(), remediateScan: vi.fn(), getQueueJob: vi.fn(),
  queueHitlReview: vi.fn(), queueHitlVerify: vi.fn(), getFileRemediationState: vi.fn(),
  getFileRemediationDiffs: vi.fn(), downloadRemediated: vi.fn(), getRules: vi.fn(),
  getRubric: vi.fn(), getConfig: vi.fn(), getCapability: vi.fn(), listHitlQueue: vi.fn(),
  updateHitlItem: vi.fn(), openTraceUrl: vi.fn(() => null), getDocumentTimeline: vi.fn(),
  confirmCriterion: vi.fn(), getExamined: vi.fn(), getTraceStatus: vi.fn(),
  getScanTraces: vi.fn(), getScanPii: vi.fn(),
}))

const { computeCoverageRows } = await import('./FileDrawer.jsx')

const opts = (over = {}) => ({
  catalogRules: null, targetLevel: 'AA', remediatedRuleIds: new Set(),
  effectiveRemediated: false, aiEnabled: true, cap: CAPABILITY_FALLBACK, ...over,
})
const idsFor = (name, over = {}) =>
  computeCoverageRows({ file: name, issues: [] }, opts(over)).map((r) => r.id).sort()

describe('the certification record covers the agreed scope, and the same list the screen shows', () => {
  it('is exactly the 14 scoped criteria for a .pdf at AA — not the 42 it used to be', () => {
    const ids = idsFor('report.pdf')
    expect(ids).toEqual([...SCOPE_SCS].sort())
    expect(ids).toHaveLength(14)
  })

  it('excludes every criterion the engagement left out of scope', () => {
    for (const fmt of ['pdf', 'docx', 'xlsx', 'pptx']) {
      const ids = idsFor(`f.${fmt}`)
      for (const sc of OUT_OF_SCOPE_SCS) expect(ids).not.toContain(sc)
    }
  })

  it('drops the AA members at a Level A target, so the record follows the target too', () => {
    // 1.4.3, 1.4.5, 2.4.6 and 3.1.2 are the AA criteria in the scope.
    const a = idsFor('report.pdf', { targetLevel: 'A' })
    expect(a).toHaveLength(10)
    for (const sc of ['1.4.3', '1.4.5', '2.4.6', '3.1.2']) expect(a).not.toContain(sc)
    expect(a.every((sc) => SCOPE_SCS.has(sc))).toBe(true)
  })

  it('keeps the criterion set format-independent — the per-format verdict is per ROW', () => {
    // The preset is per-format, but gating the row SET on it would blank the record for .html
    // (the preset covers no html pair) and hide from a .docx record the four criteria that are
    // scoped only for .pdf/.pptx. Those belong in the record as an explicit non-verdict, which is
    // what the row's own outcome says.
    for (const fmt of ['pdf', 'docx', 'xlsx', 'pptx', 'html']) {
      expect(idsFor(`f.${fmt}`)).toEqual([...SCOPE_SCS].sort())
    }
  })

  it('a finding on an out-of-scope criterion produces no row — the note is what reports it', () => {
    const rows = computeCoverageRows(
      { file: 'f.docx', issues: [{ wcag: 'SC_1_4_11', severity: 'CRITICAL' }] }, opts())
    expect(rows.find((r) => r.id === '1.4.11')).toBeUndefined()
    expect(rows.every((r) => r.outcome !== 'FAIL')).toBe(true)
  })

  it('a finding on an in-scope criterion still fails the record', () => {
    const rows = computeCoverageRows(
      { file: 'f.docx', issues: [{ wcag: 'SC_1_1_1', severity: 'CRITICAL' }] }, opts())
    expect(rows.find((r) => r.id === '1.1.1').outcome).toBe('FAIL')
  })
})
