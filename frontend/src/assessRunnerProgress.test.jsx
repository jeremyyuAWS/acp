import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// The in-flight-file line on the Assess progress panel. `currentFile` state existed from the
// day the component was written and was never rendered, so when it finally was, three separate
// things were wrong at once and none of them were visible in a diff:
//
//   1. the line referenced `ruleCount`, which was never defined — a ReferenceError that fired
//      only once a file was in flight, i.e. exactly when the feature does its job;
//   2. the immediate path (runTicker) set it to the whole file RECORD, which React refuses to
//      render as a child;
//   3. the deferred path (pollDeferred) read `.name`, a field file_records has never had —
//      store.py selects `file` — so it resolved to null and rendered nothing.
//
// Each path is exercised separately below, because they set the same state from different
// shapes and only one of them is taken per run.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const assessScan = vi.fn()
const getScan = vi.fn()
const getCapability = vi.fn()
const refreshScanDriveToken = vi.fn()
vi.mock('./api.js', () => ({
  assessScan: (...a) => assessScan(...a),
  getScan: (...a) => getScan(...a),
  getCapability: (...a) => getCapability(...a),
  refreshScanDriveToken: (...a) => refreshScanDriveToken(...a),
}))

const { default: AssessRunner } = await import('./AssessRunner.jsx')

let container, root, errSpy
const mount = async (files) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(AssessRunner, { files, runId: 's1' })) })
}
const settle = async (n = 6) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const clickText = async (t) => {
  const el = [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}
const text = () => container.textContent
// Only real failures count. React's own act-environment notice is harness noise, and swallowing
// it wholesale would swallow the ReferenceError this file exists to catch.
const realErrors = () => errSpy.mock.calls.filter(([m]) => !String(m).includes('act(...)'))

beforeEach(() => {
  assessScan.mockReset(); getScan.mockReset(); refreshScanDriveToken.mockReset()
  getCapability.mockReset().mockResolvedValue(null)
  refreshScanDriveToken.mockResolvedValue(null)
  // A render-time throw inside act() is reported through console.error rather than rejecting,
  // so assert on it directly — otherwise a ReferenceError passes as a green test.
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  try { sessionStorage.clear() } catch { /* ignore */ }
})
afterEach(() => { errSpy.mockRestore() })
afterEach(unmountAll)   // the old afterEach restored the spy but left the tree mounted

const SCORED = [
  { file: 'cardiology-handbook.pdf', type: 'pdf', score: 71, issues: [] },
  { file: 'q3-board-deck.pptx', type: 'pptx', score: 88, issues: [] },
]

describe('AssessRunner names the file it is reading', () => {
  it('deferred path: renders the first unscored file by its `file` field', async () => {
    assessScan.mockResolvedValue({ deferred: true })
    getScan.mockResolvedValue({
      run: { files: 2 },
      files: [{ file: 'done.pdf', score: 90 }, { file: 'benefits-guide.docx', score: null }],
    })
    await mount([{ file: 'benefits-guide.docx', type: 'docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(text()).toContain('benefits-guide.docx')
    expect(realErrors()).toEqual([])
  })

  it('immediate path: renders a filename, not a stringified record', async () => {
    assessScan.mockResolvedValue({ deferred: false })
    await mount(SCORED)
    await clickText('Assess')
    await settle()

    expect(text()).toContain('cardiology-handbook.pdf')
    expect(text()).not.toContain('[object Object]')
    expect(realErrors()).toEqual([])
  })

  // The count has to be derived from the level, not hardcoded: it is the agreed scope
  // (activeScope.SCOPE_SCS — the 14 criteria this engagement asked to have assessed) narrowed to
  // the levels that block at the target, which is the same lens the result tile reconciles to. At
  // A the AA members drop out — 10, not 14 — so a constant here would overstate what the
  // assessment weighs on the strictest reading. It follows the scope rather than the 20-check
  // document core because the result the progress line leads to is scored over the scope; a line
  // promising 20 ahead of a result over 14 is the mismatch this assertion exists to prevent.
  it('counts the criteria that actually block at the DERIVED level', async () => {
    assessScan.mockResolvedValue({ deferred: false })
    await mount(SCORED)
    await clickText('Assess')
    await settle()
    // The level is no longer picked here — it is DERIVED from the selected scope (deriveLevel over
    // SCOPE_SCS). This scope contains AA criteria, so the target is AA and all 14 members block.
    expect(text()).toContain('14 criteria in scope')
    // No A/AA/AAA picker any more: the blocking level follows the scope, not a second control.
    expect(container.querySelector('.lvlseg')).toBeNull()
    expect(container.querySelector('[role="radiogroup"]')).toBeNull()
  })
})

describe('AssessRunner — ignore archival/deletion filter (Deva #6)', () => {
  const toggle = () => container.querySelector('input[aria-label="Ignore files flagged for archival or deletion"]')

  it('is checked by default and assesses with archival/deletion IGNORED (override off)', async () => {
    assessScan.mockResolvedValue({ deferred: false })
    await mount(SCORED)
    expect(toggle().checked).toBe(true)
    await clickText('Assess')
    await settle()
    expect(assessScan).toHaveBeenCalledWith('s1', 'AA', false)
    expect(realErrors()).toEqual([])
  })

  it('unchecking it sends the include-flagged override so those files are assessed too', async () => {
    assessScan.mockResolvedValue({ deferred: false })
    await mount(SCORED)
    await act(async () => { toggle().dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(toggle().checked).toBe(false)
    await clickText('Assess')
    await settle()
    expect(assessScan).toHaveBeenCalledWith('s1', 'AA', true)
    expect(realErrors()).toEqual([])
  })
})
