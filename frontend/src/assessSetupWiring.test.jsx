import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

// AssessSetup reaching the screen, and the run it starts carrying the operator's decision.
//
// The component shipped to `main` as 523 lines nothing imported. That is the failure mode this
// file exists to pin: a component that renders nowhere passes every one of its own tests, reads
// as done on every status list, and leaves the screen it was written to replace in production.
// The whole frontend suite was green in exactly that state.
//
// Two lanes, because neither alone is enough. The DOM lane drives the real component and proves
// the contract works; the source lane pins the composition in App.jsx, which the DOM lane cannot
// reach without standing up the entire application.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const assessScan = vi.fn(() => Promise.resolve({ deferred: false }))
const getScan = vi.fn(() => Promise.resolve({}))
const getCapability = vi.fn(() => Promise.resolve({}))
const refreshScanDriveToken = vi.fn(() => Promise.resolve())
vi.mock('./api.js', () => ({
  assessScan: (...a) => assessScan(...a),
  getScan: (...a) => getScan(...a),
  getCapability: (...a) => getCapability(...a),
  refreshScanDriveToken: (...a) => refreshScanDriveToken(...a),
  getScanTraces: vi.fn(() => Promise.resolve([])),
  getQueueJob: vi.fn(() => Promise.resolve(null)),
  getJobs: vi.fn(() => Promise.resolve({ workers: 0, stats: { running: 0, queued: 0 }, worker_tier_alive: false })),
  setWorkers: vi.fn(() => Promise.resolve({ workers: 0 })),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
}))

const { default: AssessRunner } = await import('./AssessRunner.jsx')

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

const FILES = [
  { file: 'a.docx', name: 'a.docx', status: 'done', score: 90 },
  { file: 'b.pdf', name: 'b.pdf', status: 'done', score: 80 },
]

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(AssessRunner, { files: FILES, runId: 's1', ...props }))
  })
}
const settle = async (n = 6) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

// AssessRunner persists its phase to sessionStorage keyed by runId and reads it back on mount
// (`loadSaved`). Without this clear, the first test to complete a run leaves phase='running'
// behind, and every later test mounting the same runId returns early from `assess()` — the
// symptom being zero API calls and an assertion that looks like broken wiring.
afterEach(() => { unmountAll(); vi.clearAllMocks(); sessionStorage.clear() })

describe('AssessSetup drives the run (approved board 2)', () => {
  it('renders its own Run button when uncontrolled — the pre-existing behaviour', async () => {
    await mount({})
    const buttons = [...container.querySelectorAll('button')].map((b) => b.textContent)
    expect(buttons.some((t) => /Assess \d/.test(t))).toBe(true)
  })

  it('renders NO run button when controlled, so the screen carries one and not two', async () => {
    await mount({ controlled: true })
    const buttons = [...container.querySelectorAll('button')].map((b) => b.textContent)
    expect(buttons.some((t) => /^▶ Assess \d/.test(t))).toBe(false)
    // The lifecycle toggle goes with it. Two independent copies of the same override, one of them
    // hidden inside a collapsed panel, is how a screen ends up disagreeing with the request it sends.
    expect(container.querySelector('.assess-lifecycle-ignore')).toBe(null)
  })

  it('hands out a start function that carries the pre-run screen decision to the API', async () => {
    let start = null
    await mount({ controlled: true, onReady: (fn) => { start = fn } })
    expect(typeof start).toBe('function')

    await act(async () => {
      start({ level: 'AA', includeLifecycleFlagged: true })
    })
    await settle()

    expect(assessScan).toHaveBeenCalled()
    const [runId, level, includeFlagged] = assessScan.mock.calls[0]
    expect(runId).toBe('s1')
    expect(level).toBe('AA')
    // TRUE, from the descriptor. The runner's own `ignoreLifecycle` state defaults to true, which
    // would send FALSE here — so this asserts the operator's choice won, not the hidden default.
    expect(includeFlagged).toBe(true)
  })

  it('honours an exclude decision too, so the assertion above is not passing on a constant', async () => {
    let start = null
    await mount({ controlled: true, onReady: (fn) => { start = fn } })
    await act(async () => { start({ level: 'AA', includeLifecycleFlagged: false }) })
    await settle()
    expect(assessScan.mock.calls[0][2]).toBe(false)
  })

  it('refreshes the Drive token before assessing, on the externally-started path too (ADR 0020)', async () => {
    let start = null
    await mount({ controlled: true, onReady: (fn) => { start = fn } })
    await act(async () => { start({ level: 'AA', includeLifecycleFlagged: false }) })
    await settle()
    // The stale-token gap is not something the pre-run screen should be able to bypass.
    expect(refreshScanDriveToken).toHaveBeenCalledWith('s1')
  })
})

describe('App composes the Assess tab the way the board specifies', () => {
  const app = () => read('App.jsx')

  it('mounts AssessSetup', () => {
    expect(app()).toMatch(/<AssessSetup\b/)
    expect(app()).toMatch(/import AssessSetup from '\.\/AssessSetup\.jsx'/)
  })

  it('puts AssessRunner in controlled mode, so only one Run button reaches the page', () => {
    expect(app()).toMatch(/<AssessRunner[\s\S]{0,240}?controlled\b/)
  })

  it('removes the two collapsed scope panels the board deletes', () => {
    // "Removed from this screen: the WCAG scope-rules panel (hidden), the capability scorecard
    // (now a reference page), and the results scaffolding that rendered before any run existed."
    expect(app()).not.toMatch(/<AssessScope\s*\/>/)
    expect(app()).not.toMatch(/<ScopeRules\s*\/>/)
    // and their imports go with them, or the next reader assumes the screen still uses them
    expect(app()).not.toMatch(/import AssessScope from/)
    expect(app()).not.toMatch(/import ScopeRules from/)
  })

  it('shows the pre-run screen only before a run, never beside the results', () => {
    // Both guards matter and they are different: assessPhase covers the run in flight, `assessed`
    // covers a scan assessed in an earlier session that this browser is reopening.
    // The window has to clear the explanatory comment that sits between the guard and the mount.
    // The quantifier is LAZY, so this still matches the nearest AssessSetup after the guard — it
    // proves the guard immediately precedes the mount, not merely that both exist in the file.
    expect(app()).toMatch(/assessPhase === 'idle' && !assessed && \([\s\S]{0,600}?<AssessSetup/)
  })

  it('shows the results for a scan assessed in an EARLIER session, not only after a run this session', () => {
    // The regression from the empty-panel report: results gated PURELY on assessPhase === 'done'
    // left a scan assessed in a prior session showing a blank Assess tab on reload — AssessSetup is
    // hidden by `assessed`, and the results were hidden by 'done' (assessPhase is 'idle' because
    // AssessRunner's per-session cache is gone). The gate must also admit a persisted (assessed_at)
    // scan that was NOT assessed this session, while still hiding results during a live run.
    const s = app()
    // resultsReady is the two-way gate: finished this session (done) OR a prior-session assessed scan.
    expect(s).toMatch(/const resultsReady =[\s\S]{0,80}assessPhase === 'done'[\s\S]{0,120}?assessed_at[\s\S]{0,60}?justAssessed !== run\?\.id/)
    // the results are gated on it…
    expect(s).toMatch(/assessed && resultsReady && !runDetails && !assessFile && <><AssessSummary/)
    // …and NOT purely on 'done' any more (the exact shape that produced the empty panel).
    expect(s).not.toMatch(/assessed && assessPhase === 'done' && !runDetails/)
  })

  it('A13 · wires document-to-document navigation from the worklist order', () => {
    // AssessFileFindings has always supported onNext/nextName; the Assess tab never passed them, so
    // no cross-document nav shipped. The order must be the worklist's own — documentRows — or "next"
    // would disagree with the list the reader came from.
    const s = app()
    expect(s).toMatch(/import \{ documentRows \} from '\.\/assessMetrics\.js'/)
    expect(s, 'the nav order is not taken from documentRows').toMatch(/documentRows\(files,[\s\S]{0,60}?\.filter\(\(r\) => r\.opened\)/)
    expect(s, 'onNext is not wired to the computed next row').toMatch(/<AssessFileFindings[\s\S]{0,400}?onNext=\{assessFileNext/)
    expect(s).toMatch(/nextName=\{assessFileNext\?\.name\}/)
  })

  it('A1 · passes the assessed timestamp to the summary, FORMATTED', () => {
    // Same rule as the discovery stamp below: the raw assessed_at column must never reach a screen.
    expect(app()).toMatch(/<AssessSummary[\s\S]{0,300}?assessedAt=\{fmtStamp\(run\?\.assessed_at\)\}/)
  })

  it('seven states · passes the run to the summary, so a stopped or failed run is classified as one', () => {
    // The file list alone cannot distinguish a partial or failed run from a complete one — the run's
    // own status can. Without this prop AssessSummary can only ever render the completed states.
    expect(app()).toMatch(/<AssessSummary[\s\S]{0,400}?\brun=\{run\}/)
  })

  it('board 5 · feeds the raw file record and the assessed stamp to the one-file view', () => {
    // AssessFileFindings' `row` prop is a documentRow — it carries no size, no Drive id and no
    // timestamp. Those live only on the raw file record, so App must look it up and pass it
    // separately (`file=`), alongside the run's own assessed_at, formatted.
    const s = app()
    expect(s).toMatch(/const assessFileRaw = useMemo\(/)
    expect(s).toMatch(/<AssessFileFindings[\s\S]{0,120}?\bfile=\{assessFileRaw\}/)
    expect(s).toMatch(/<AssessFileFindings[\s\S]{0,200}?assessedAt=\{fmtStamp\(run\?\.assessed_at\)\}/)
  })

  it('A28 · wires the worklist bulk-fix to the scoped remediateScan call, with run.id supplied at the call site', () => {
    // handleBulkFix is declared BEFORE `run` exists (run is derived after this component's only
    // early return) so it cannot close over run.id directly — the same hook-order constraint that
    // shaped assessFileNext. run.id is supplied by the JSX call site instead, which is past that
    // return and has it in scope.
    const s = app()
    expect(s).toMatch(/import \{[^}]*remediateScan[^}]*\} from '\.\/api'/)
    expect(s).toMatch(/const handleBulkFix = useCallback\(async \(scanId, rows\) => \{/)
    expect(s).toMatch(/<AssessWorklist[\s\S]{0,200}?onBulkFix=\{\(rows\) => handleBulkFix\(run\.id, rows\)\}/)
  })

  it('state 4 · feeds the not-started count from the backend so the partial banner can name it', () => {
    // get_scan exposes run.not_assessed for a stopped run (the documents the scope selected but the
    // run never assessed — they are not in the file list). Passing its count lets the partial banner
    // say "N documents were never started" rather than only "of the M assessed".
    expect(app()).toMatch(/<AssessSummary[\s\S]{0,500}?notStarted=\{run\?\.not_assessed\?\.count\}/)
  })

  it('passes the discovery timestamp FORMATTED, never the raw column', () => {
    // This assertion previously pinned `discoveredAt={run.completed_at || null}` and passed while
    // the screen was wrong. AssessSetup interpolates the value straight into "From discovery run
    // {discoveredAt}" and formats nothing, so the raw column rendered an ISO timestamp across the
    // top of the Assess tab. Pinning the prop EXPRESSION is not the same as pinning that the value
    // is presentable — this now requires the formatter.
    expect(app()).toMatch(/discoveredAt=\{fmtStamp\(/)
    expect(app()).not.toMatch(/discoveredAt=\{run\??\.?completed_at/)
  })

  it('formats it with the same helper the rest of the run header uses', () => {
    // Not a second date format invented for one screen: fmtStamp is what the run-info bar and the
    // time-travel banner already print, and it returns null for a missing value — which is exactly
    // AssessSetup's "omitted renders no line at all rather than an invented one" contract.
    expect(app()).toMatch(/function fmtStamp\(iso\) \{\n\s*if \(!iso\) return null/)
  })

  it('board 3 · Stop moves into the running card, but only while THAT card is the one showing', () => {
    // The shared scan-progress banner's own Stop button is suppressed specifically when
    // view === 'assess' && assessPhase === 'running' — every other case (Discover scanning, or
    // viewing a different tab while a scan runs in the background) must keep it, since nothing
    // else offers a Stop control there. Getting this guard backwards would silently remove Stop
    // from Discover, which is the one regression this whole relocation was held back over earlier.
    const s = app()
    expect(s).toMatch(/!\(view === 'assess' && assessPhase === 'running'\) && \([\s\S]{0,320}?Stop scan/)
    expect(s).toMatch(/<LiveAssessmentLive[\s\S]{0,150}?onStop=\{\(\) => cancelScan\(liveScanId\)/)
  })
})

describe('the Discover nav tab only checks off once discovery has actually FINISHED', () => {
  // `run` is truthy the instant a scan record exists client-side — even one still `status:
  // 'running'`, mid-listing. `!!run` alone put a green checkmark on the Discover tab while a scan
  // was still in flight, which is exactly the state that produced a live report: Discover showing
  // a real, growing file count with its own tab already checked off, while Assess correctly said
  // "no discovery run has listed an estate yet" (it reads completed_at, the same gate
  // /assess/eligibility uses) — two truthful signals that read as a contradiction because one of
  // them was answering the wrong question.
  it('keys the Discover stage-done flag off completed_at, not off a scan merely existing', () => {
    const s = read('App.jsx')
    expect(s).toMatch(/discover: !!run\?\.completed_at/)
    expect(s, 'the old premature form is still present').not.toMatch(/discover: !!run,/)
  })
})
