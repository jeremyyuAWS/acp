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
    expect(app()).toMatch(/assessPhase === 'idle' && !assessed && \([\s\S]{0,200}?<AssessSetup/)
  })

  it('passes the discovery timestamp, and passes nothing when there is none', () => {
    // AssessSetup omits the header line entirely rather than inventing a date, so the `|| null`
    // is load-bearing: `undefined` would be a prop React drops, and the component's default would
    // still be null — but an empty string would render as a line with no date in it.
    expect(app()).toMatch(/discoveredAt=\{run\.completed_at \|\| null\}/)
  })
})
