import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

// ── The reported screen, rendered ─────────────────────────────────────────────────────────────
// Observed live 2026-07-30 on production v2026.7.29.8 (commit 9dc2ac4), a build that already
// contained #84 and #86:
//
//     MASTER SCORE   0 avg/100 · 0 certifiable · 2 issues · 0 uncertain · 0 unanalysable · 2 files
//     rows           acme-fy2026-summary.xlsx                          clean   n/a   clean
//                    assessment-applicability-matrix-28JUL-Final.xlsx   clean   n/a   clean
//     drawer         🔴 1 issue needs remediation · 12 / 38 coverage
//
// The unit tests pin the derivations. This one renders the actual Dashboard against the actual
// row shape and reads the words off the screen, because every one of those numbers was produced
// by code that each of its own unit tests would have passed.
//
// Run against the pre-fix modules it reproduces the report character for character — this is the
// rendered text, verbatim, with only the whitespace the DOM omits:
//
//     0certifiable 2issues 0uncertain 0unanalysable = 2files
//     acme-fy2026-summary.xlsx  Google Drive  clean  n/a  clean
//     assessment-applicability-matrix-28JUL-Final.xlsx  Google Drive  clean  n/a  clean
//
// Note what "2 issues" costs a SCORED, genuinely clear document too: rendering one clean file
// pre-fix produced "0certifiable 1issues", because 'clean' had no tile and the amber bucket was
// a remainder. The unscored estate is the reported case, not the only one.

vi.mock('./api.js', () => ({
  openReport: vi.fn(),
  getScanDiff: vi.fn(() => Promise.resolve(null)),
  getFileStatus: vi.fn(() => Promise.resolve({ available: false })),
  getScanStatus: vi.fn(() => Promise.resolve({ available: false })),
  getRules: vi.fn(() => Promise.resolve(null)),
  getRubric: vi.fn(() => Promise.resolve(null)),
  getConfig: vi.fn(() => Promise.resolve(null)),
  getCapability: vi.fn(() => Promise.resolve(null)),
  getFileRemediationState: vi.fn(() => Promise.resolve([])),
  getFileRemediationDiffs: vi.fn(() => Promise.resolve([])),
  getDocumentTimeline: vi.fn(() => Promise.resolve([])),
  listHitlQueue: vi.fn(() => Promise.resolve([])),
  getExamined: vi.fn(() => Promise.resolve(null)),
  explainFinding: vi.fn(() => Promise.resolve(null)),
  getFileContent: vi.fn(() => Promise.resolve(null)),
  uploadToDrive: vi.fn(), markRemediated: vi.fn(), remediateScan: vi.fn(),
  getQueueJob: vi.fn(), queueHitlReview: vi.fn(), queueHitlVerify: vi.fn(),
  updateHitlItem: vi.fn(), openTraceUrl: vi.fn(), confirmCriterion: vi.fn(),
  downloadRemediated: vi.fn(),
}))

const { default: Dashboard } = await import('./Dashboard.jsx')

// The ADR 0020 inventory-fallback row shape, verbatim from api/store.py get_scan: listed from the
// source's metadata, never opened, so every score/finding field is null or empty.
const unopened = (file, sizeKb) => ({
  file, engine: 'inventory', status: 'discovered', score: null, compliant: 0, skipped_rules: 0,
  remediated_at: null, drive_write_url: null, acp_stamped: null, published_at: null,
  size_kb: sizeKb, pages: null, sheets: null, drive_file_id: null, sourceName: 'Google Drive',
  issues: [], tags: [],
})

const FILES = [
  unopened('acme-fy2026-summary.xlsx', 88),
  unopened('assessment-applicability-matrix-28JUL-Final.xlsx', 132),
]
// The run row as _fill_run_aggregate hands it out for a scan whose file_records are empty:
// counters derived over zero rows, avg_score genuinely unknown.
const RUN = { id: 'scan-live', status: 'discovered', files: 2, certifiable: 0, uncertain: 0,
              error: 0, avg_score: null, completed_at: '2026-07-30T09:00:00Z' }

let container, root
beforeEach(() => {
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
})
// Unmount, rather than leaving the tree standing for the environment teardown to race.
//
// Dashboard's scan-diff useEffect resolves a promise and calls setDiff, so a root left mounted
// keeps work in React's concurrent scheduler after the last assertion. When jsdom is torn down
// first, that work reaches `getActiveElementDeep` and throws `ReferenceError: window is not
// defined` as an UNHANDLED error — every test still reports passed, and vitest exits non-zero on
// the error count alone. Observed once in a full-suite run under load (right after an
// `npm install`) and never in six isolated runs or three later full runs, which is exactly the
// profile of a test that fails a CI job one time in many and gets re-run rather than fixed.
afterEach(async () => {
  await act(async () => { root.unmount() })
  container.remove()
})
const render = async (props) => {
  await act(async () => { root.render(createElement(Dashboard, props)) })
  return container.textContent
}

describe('the reported screen tells the truth about two unscored documents', () => {
  it('does not call either row clean, in the status column or the findings column', async () => {
    const t = await render({ run: RUN, files: FILES, scanList: [{ id: RUN.id }] })

    // Not the word anywhere in the inventory — it appeared twice per row before (status badge
    // and findings cell), about documents nobody had opened.
    expect(t).not.toMatch(/\bclean\b/)
    expect(t).toContain('not assessed')
    // The score is still honestly absent; that part was never wrong.
    expect(t).toContain('n/a')
  })

  it('does not report issues over rows that carry no findings', async () => {
    const t = await render({ run: RUN, files: FILES, scanList: [{ id: RUN.id }] })

    // "2 issues" came from `run.files - certifiable - uncertain - error`. No document here has a
    // single finding, so no issue count may be non-zero.
    expect(FILES.every((f) => f.issues.length === 0)).toBe(true)
    expect(t).not.toMatch(/2\s*issues/)
    expect(t).toMatch(/0\s*issues/)
    // …and the documents are accounted for, in the bucket that says nobody measured them.
    expect(t).toMatch(/2\s*not assessed/)
  })

  it('accounts for every document exactly once across the hero tiles', async () => {
    const t = await render({ run: RUN, files: FILES, scanList: [{ id: RUN.id }] })
    // The "= N files" tile is the SUM of the tiles beside it, and the tiles now partition the
    // estate rather than one of them being a remainder.
    expect(t).toMatch(/=\s*2\s*files/)
    expect(t).toMatch(/0\s*certifiable/)
  })

  it('offers a filter for the bucket the documents are actually in', async () => {
    const t = await render({ run: RUN, files: FILES, scanList: [{ id: RUN.id }] })
    // Pre-fix the chip list was hardcoded to certifiable/issues/uncertain/unanalysable, so this
    // estate had no chip at all for the state all of its documents were in.
    expect(t).toMatch(/not assessed\s*2/)
  })

  it('still says clean about a document that WAS opened and scored clear', async () => {
    // The other half of the rule: this fix must not turn a real "no findings" into a hedge.
    const scored = { ...unopened('board-minutes-accessible.docx', 40),
                     status: 'analysed', score: 100, engine: 'docx' }
    const t = await render({
      run: { ...RUN, files: 1, avg_score: 100 },
      files: [scored], scanList: [{ id: RUN.id }],
    })
    expect(t).toContain('no findings')
    expect(t).toContain('100')
    // The unscored tile is present-and-zero rather than absent (a reviewer wants "0 not
    // assessed" confirmed), so assert the COUNT is zero rather than that the words are missing.
    expect(t).toMatch(/0\s*not assessed/)
    expect(t).toMatch(/1\s*no findings/)
    // And the row itself carries the affirmative verdict, in both columns.
    expect(t).toMatch(/board-minutes-accessible\.docx.*no findings.*100.*clean/)
  })
})
