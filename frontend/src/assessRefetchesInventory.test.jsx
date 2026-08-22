import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

// ── The inventory is never refetched when the assessment completes ────────────────────────────
// Production Log Analytics for scan 14808f34bdf3 (2026-07-30):
//
//     02:00:42  POST /scans?source=drive&…&fanout=true    → discover only
//     02:00:50  GET  …/files/acme-fy2026-summary.xlsx/examined · /status · /remediation-state
//                                                         ← rows rendered HERE, pre-Assess
//     02:01:05  POST /scans/14808f34bdf3/assess?level=AA  ← 15s later
//     02:01:13  worker: …-28JUL-Final.xlsx: 2 finding(s) in 3.4s
//     02:01:16  worker: acme-fy2026-summary.xlsx: 5 finding(s) in 5.9s
//
// ACP_DEFER_ANALYSIS_TO_ASSESS=1 on acp-app, so Discover wrote only scan_inventory and
// store.get_scan served the ADR 0020 inventory fallback (status 'discovered', score null,
// issues []). Seven findings existed by 02:01:16 and the rows still said "not assessed",
// because the only GET of this scan happened at 02:00:50 and nothing fetched it again.
//
// This is NOT the contradiction #101 fixed — that one made these rows stop claiming "clean"
// about documents nobody had opened, and it stands. What is left is narrower: the rows are
// honest and stale. The drawer answers correctly beside them, which is what makes the
// staleness visible rather than merely theoretical.

vi.mock('./api.js', () => ({
  // Fetched by AssessRunner. getScan is the one under test: it returns the pre-Assess inventory
  // until `serving` is flipped, exactly as production did between 02:00:50 and 02:01:16.
  getScan: vi.fn(() => Promise.resolve(serving)),
  assessScan: vi.fn(() => Promise.resolve(ASSESS_ACCEPTED)),
  refreshScanDriveToken: vi.fn(() => Promise.resolve({ ok: true })),
  getScanTraces: vi.fn(() => Promise.resolve([])),
  getTraceStatus: vi.fn(() => Promise.resolve(null)),
  // Fetched by the inventory + the drawer it opens.
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
  getJobs: vi.fn(() => Promise.resolve({ workers: 0, stats: { running: 0, queued: 0 }, worker_tier_alive: false })),
  setWorkers: vi.fn(() => Promise.resolve({ workers: 0 })),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
}))

const SID = '14808f34bdf3'

// What POST /scans/{sid}/assess returns in the deferred model: accepted, nothing assessed yet.
// No assessed_at — that is stamped at finalize, ~11s later. A refetch triggered off THIS would
// re-read the same inventory fallback and change nothing, which is why the fix cannot hang here.
const ASSESS_ACCEPTED = { phase: 'assessing', deferred: true }

// The ADR 0020 inventory-fallback row: listed from Drive metadata, never opened.
const unopened = (file, sizeKb) => ({
  file, engine: 'inventory', status: 'discovered', score: null, compliant: 0, skipped_rules: 0,
  remediated_at: null, drive_write_url: null, acp_stamped: null, published_at: null,
  size_kb: sizeKb, pages: null, sheets: null, drive_file_id: null, sourceName: 'Google Drive',
  issues: [], tags: [],
})
// The same document after the worker opened it — the finding counts are the ones in the log.
const analysed = (row, score, n) => ({
  ...row, engine: 'xlsx', status: 'analysed', score,
  issues: Array.from({ length: n }, (_, i) => ({
    rule_id: `SC_1_1_${i + 1}`, wcag: `SC_1_1_${i + 1}`, severity: 'serious',
    detail: `finding ${i + 1}`,
  })),
})

const SUMMARY = unopened('acme-fy2026-summary.xlsx', 88)
const MATRIX = unopened('assessment-applicability-matrix-28JUL-Final.xlsx', 132)

// 02:00:50 — what every surface in the app was holding.
const PRE_ASSESS = {
  run: { id: SID, status: 'discovered', files: 2, certifiable: 0, uncertain: 0, error: 0,
         avg_score: null, assessed_at: null, finalized_at: null,
         completed_at: '2026-07-30T02:00:42Z' },
  files: [SUMMARY, MATRIX],
}
// 02:01:16 — what the server would have handed back, had anyone asked.
const POST_ASSESS = {
  run: { ...PRE_ASSESS.run, status: 'assessed', avg_score: 62,
         assessed_at: '2026-07-30T02:01:16Z' },
  files: [analysed(SUMMARY, 55, 5), analysed(MATRIX, 70, 2)],
}

let serving = PRE_ASSESS

const { default: AssessRunner } = await import('./AssessRunner.jsx')
const { default: Dashboard } = await import('./Dashboard.jsx')
const { useScanRefetch } = await import('./scanRefetch.js')
const api = await import('./api.js')

let container, root, seen
beforeEach(() => {
  serving = PRE_ASSESS
  seen = []
  window.addEventListener('acp:scan-assessed', onSignal)
  sessionStorage.clear()
  vi.clearAllMocks()
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
})
const onSignal = (e) => seen.push(e.detail)
// Unmount rather than leaving the tree for jsdom teardown to race — see the note in
// inventoryAgreesWithDrawer.test.jsx: a root left mounted keeps promise-driven setState in
// React's scheduler and fails the RUN, not the test, on the unhandled-error count alone.
afterEach(async () => {
  window.removeEventListener('acp:scan-assessed', onSignal)
  await act(async () => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

const flush = async (n = 3) => { for (let i = 0; i < n; i++) await act(async () => {}) }

describe('a deferred assessment tells the app to re-read the scan when it finalizes', () => {
  it('does not announce on the POST — only once the worker has actually finished', async () => {
    vi.useFakeTimers()
    await act(async () => {
      root.render(createElement(AssessRunner, { files: PRE_ASSESS.files, runId: SID }))
    })
    // Pre-Assess the estate is assessABLE, not excluded: two discovered files, none scored.
    expect(container.textContent).toMatch(/Assess 2 files/)

    await act(async () => { container.querySelector('button.assessbtn').click() })
    await flush()

    // The POST resolved {phase:'assessing', deferred:true} and the first poll saw no
    // assessed_at. Announcing here is the trap: the scan still serves the inventory fallback,
    // so a refetch would repaint the identical "not assessed" rows and read as fixed.
    // Third arg is the include-lifecycle-flagged override; false by default (archival/deletion ignored).
    expect(api.assessScan).toHaveBeenCalledWith(SID, 'AA', false)
    expect(serving).toBe(PRE_ASSESS)
    expect(seen).toEqual([])

    // 02:01:16 — the worker finishes and finalize stamps assessed_at.
    serving = POST_ASSESS
    await act(async () => { vi.advanceTimersByTime(2000) })
    await flush()

    // Announced exactly once, naming the scan so the listener refetches THAT scan rather than
    // whichever one the tab happens to be holding.
    expect(seen).toEqual([{ scanId: SID }])
  })

  it('announces once per run, not once per poll after it finished', async () => {
    vi.useFakeTimers()
    await act(async () => {
      root.render(createElement(AssessRunner, { files: PRE_ASSESS.files, runId: SID }))
    })
    await act(async () => { container.querySelector('button.assessbtn').click() })
    await flush()
    serving = POST_ASSESS
    await act(async () => { vi.advanceTimersByTime(2000) })
    await flush()
    // The poll clears its own interval at finalize. If it did not, every subsequent tick would
    // re-announce and App would refetch the scan every two seconds for as long as the tab lived.
    await act(async () => { vi.advanceTimersByTime(20_000) })
    await flush()
    expect(seen).toEqual([{ scanId: SID }])
  })

  it('persists "done" before announcing, so the refetch cannot restart the poller', async () => {
    vi.useFakeTimers()
    await act(async () => {
      root.render(createElement(AssessRunner, { files: PRE_ASSESS.files, runId: SID }))
    })
    await act(async () => { container.querySelector('button.assessbtn').click() })
    await flush()
    serving = POST_ASSESS
    await act(async () => { vi.advanceTimersByTime(2000) })
    await flush()

    // The announcement changes `files` under this component, which moves `docs.length` from 0 to
    // 2 — the dependency of the resume effect. That effect re-reads sessionStorage, so if the
    // saved phase were still 'running' + deferred it would start a SECOND poller over a run that
    // has already finished.
    expect(JSON.parse(sessionStorage.getItem(`acp-assess-${SID}`)).phase).toBe('done')

    // Re-render with the refetched files, as App does, and confirm nothing resumes.
    const before = api.getScan.mock.calls.length
    await act(async () => {
      root.render(createElement(AssessRunner, { files: POST_ASSESS.files, runId: SID }))
    })
    await flush()
    await act(async () => { vi.advanceTimersByTime(6000) })
    await flush()
    expect(api.getScan.mock.calls.length).toBe(before)
    expect(seen).toEqual([{ scanId: SID }])
  })
})

describe('the refetched payload is what stops the rows saying "not assessed"', () => {
  const render = async (payload) => {
    await act(async () => {
      root.render(createElement(Dashboard, {
        run: payload.run, files: payload.files, scanList: [{ id: SID }],
      }))
    })
    return container.textContent
  }

  it('reproduces the reported rows from the payload the screen was holding', async () => {
    const t = await render(PRE_ASSESS)
    // Honest, and #101's doing — but by 02:01:16 it was no longer true of either document.
    expect(t).toMatch(/2\s*not assessed/)
    expect(t).toMatch(/acme-fy2026-summary\.xlsx.*not assessed.*n\/a.*not assessed/)
    expect(t).not.toMatch(/issue\(s\)/)
  })

  it('shows each document its findings once the scan has been re-read', async () => {
    const t = await render(POST_ASSESS)
    // The seven findings the worker logged, on the rows they belong to.
    expect(t).toMatch(/acme-fy2026-summary\.xlsx.*55.*5 issue\(s\)/)
    expect(t).toMatch(/assessment-applicability-matrix-28JUL-Final\.xlsx.*70.*2 issue\(s\)/)
    // No document is in the unmeasured bucket any more, and none of them is called clean.
    expect(t).toMatch(/0\s*not assessed/)
    expect(t).not.toMatch(/\bclean\b/)
    expect(t).toMatch(/2\s*issues/)
  })
})

// ── The reported screen, all the way through ──────────────────────────────────────────────────
// The two halves above are each true in isolation and the bug lived between them. So wire them
// together with the REAL refetch (useScanRefetch — the hook App.jsx calls, not a copy of it) and
// read the rows off the screen either side of the assessment, the way the owner did at 02:01.
describe('the inventory stops saying "not assessed" once the assessment finishes', () => {
  const Screen = () => {
    const [scan, setScan] = useState(PRE_ASSESS)
    useScanRefetch(scan?.run?.id, setScan)
    return createElement('div', null,
      createElement(AssessRunner, { files: scan.files, runId: scan.run.id }),
      createElement(Dashboard, { run: scan.run, files: scan.files, scanList: [{ id: SID }] }))
  }

  it('re-reads the scan when the run finalizes, and the rows show the findings', async () => {
    vi.useFakeTimers()
    await act(async () => { root.render(createElement(Screen)) })
    await flush()

    // 02:00:50 — the reported screen. Two documents listed from Drive metadata, never opened.
    expect(container.textContent).toMatch(/2\s*not assessed/)
    expect(container.textContent).not.toMatch(/issue\(s\)/)

    // 02:01:05 — Assess. The POST is accepted and stamps no assessed_at, so nothing may change
    // yet: the scan still serves the inventory fallback for another ~11 seconds.
    await act(async () => { container.querySelector('button.assessbtn').click() })
    await flush()
    expect(container.textContent).toMatch(/2\s*not assessed/)

    // 02:01:10–02:01:16 — the worker opens both documents and finalize stamps assessed_at.
    serving = POST_ASSESS
    await act(async () => { vi.advanceTimersByTime(2000) })
    await flush()

    // This is the assertion the whole change exists for. Pre-fix it fails here — the run is
    // finished, the drawer would answer correctly, and the rows are still on the 02:00:50 payload.
    const t = container.textContent
    // No document is in the unmeasured bucket any more. Asserted as a zero COUNT rather than as
    // the absent phrase, because the tile stays visible at zero on purpose (#101) — "0 not
    // assessed" is a fact a reviewer wants confirmed.
    expect(t).toMatch(/0\s*not assessed/)
    expect(t).not.toMatch(/2\s*not assessed/)
    expect(t).toMatch(/acme-fy2026-summary\.xlsx.*55.*5 issue\(s\)/)
    expect(t).toMatch(/assessment-applicability-matrix-28JUL-Final\.xlsx.*70.*2 issue\(s\)/)
    // Refetched the scan that was announced, not merely the one this tab was holding.
    expect(api.getScan).toHaveBeenCalledWith(SID)
  })

  it('still refetches on a remediation — the listener it shares (#86)', async () => {
    await act(async () => { root.render(createElement(Screen)) })
    await flush()
    expect(container.textContent).toMatch(/2\s*not assessed/)

    serving = POST_ASSESS
    await act(async () => {
      window.dispatchEvent(new CustomEvent('acp:file-remediated',
                                           { detail: { scanId: SID, file: SUMMARY.file } }))
    })
    await flush()
    expect(container.textContent).toMatch(/5 issue\(s\)/)
  })
})
