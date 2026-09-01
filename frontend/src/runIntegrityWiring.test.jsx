import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import { runIntegrity, integrityCaveat } from './runIntegrity.js'

// The gate, actually on the screen and actually qualifying the result beside it.
//
// A verdict nothing renders is worth exactly nothing, and this repo has the scar: ten components
// landed on main unmounted and every one read as shipped, because a component that is never
// mounted and one mounted with the wrong props both render blank (see remediateWiring.test.jsx).
// The gate has the same shape — AssessRunIntegrity returns a panel that is easy to leave out, and
// AssessSummary's caveat is null on a complete run, so "wired" and "always silent" look identical.
//
// Composition is asserted at source level for App.jsx, which is far too large to mount; the
// BEHAVIOUR of the summary's caveat is asserted by mounting the summary, because that is the line
// a reader actually reads.

const here = dirname(fileURLToPath(import.meta.url))
// Comments stripped before every assertion: a comment naming a component is not a mount, and the
// comments here necessarily quote the prop names they explain.
const code = (f) => readFileSync(join(here, f), 'utf8')
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

const app = code('App.jsx')

describe('the gate is composed into the Assess screen', () => {
  it('renders the integrity panel', () => {
    expect(app).toMatch(/<AssessRunIntegrity\b/)
  })

  it('renders it BEFORE the summary, so the caveat is above the result it qualifies', () => {
    expect(app.indexOf('<AssessRunIntegrity')).toBeLessThan(app.indexOf('<AssessSummary'))
    expect(app.indexOf('<AssessRunIntegrity')).toBeGreaterThan(-1)
  })

  it('passes the verdict to the summary as well, so the two cannot disagree', () => {
    expect(app).toMatch(/<AssessSummary[\s\S]{0,600}?integrityCaveat=\{integrityCaveat\(runVerdict\)\}/)
  })

  it('reads the coverage record once and shares it', () => {
    // Two fetches would be two round trips and, worse, two answers.
    expect(app.match(/useScanManifest\(/g)).toHaveLength(1)
    expect(app).toMatch(/<AssessRunIntegrity[^>]*verdict=\{runVerdict\}/)
  })

  it('tells the verdict which scan is on screen, which is the staleness check that survives a reload', () => {
    expect(app).toMatch(/currentScanId:\s*run\?\.id/)
  })

  it('reads the manifest ABOVE the signed-out early return', () => {
    // Not tidiness — correctness. App returns <SignIn/> early when `me` is absent, so a hook
    // below that line runs on a signed-in render and not on a signed-out one, and React counts
    // the difference: "Rendered more hooks than during the previous render". Placed below, this
    // one hook failed 24 tests across five App-mounting files at once, and the error names the
    // symptom rather than the rule — which is why the rule is asserted here.
    //
    // The verdict itself is computed below the return, and may be: runIntegrity is a plain
    // function, not a hook.
    const hook = app.indexOf('useScanManifest(')
    const signedOutReturn = app.indexOf('if (!me) return <SignIn')
    expect(hook).toBeGreaterThan(-1)
    expect(signedOutReturn).toBeGreaterThan(-1)
    expect(hook).toBeLessThan(signedOutReturn)
  })
})

// ── the caveat, as a reader meets it ──────────────────────────────────────────────────────
const { default: AssessSummary } = await import('./AssessSummary.jsx')

const mountSummary = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(AssessSummary, {
      files: [{ file: 'a.docx', status: 'analysed', score: 100, issues: [] }],
      cap: {}, assessment: {}, run: { id: 'run-1', status: 'done' }, ...props,
    }))
  })
  return container
}

afterEach(unmountAll)

const manifest = (over = {}) => ({
  scan_id: 'run-1', files_total: 1,
  rules_expected_total: 34, rules_checked_total: 34, rules_errored_total: 0,
  rules_not_checked_total: 0, rules_errored_unattributed_total: 0,
  rules_not_applicable_total: 0, completeness_pct: 100, complete: true, files: [], ...over,
})

describe('the summary carries the caveat beside its status', () => {
  it('prints it when coverage is incomplete', async () => {
    const caveat = integrityCaveat(runIntegrity(manifest({
      complete: false, rules_checked_total: 17, rules_not_checked_total: 17,
    })))
    const c = await mountSummary({ integrityCaveat: caveat })
    expect(c.textContent).toContain('17 of 34 applicable checks completed — not a conformance result.')
  })

  it('prints nothing at all when the run is genuinely complete', async () => {
    // The gate has to be able to go quiet, or people learn to ignore it.
    const c = await mountSummary({ integrityCaveat: integrityCaveat(runIntegrity(manifest())) })
    expect(c.textContent).not.toMatch(/conformance result/i)
  })

  it('announces the caveat rather than leaving it as decoration', async () => {
    const c = await mountSummary({ integrityCaveat: 'Run coverage is unknown — not a conformance result.' })
    const statuses = [...c.querySelectorAll('[role="status"]')].map((n) => n.textContent)
    expect(statuses.some((s) => s.includes('not a conformance result'))).toBe(true)
  })

  it('keeps working when nothing is passed, so an un-wired caller degrades quietly', async () => {
    const c = await mountSummary({})
    expect(c.textContent).toBeTruthy()
  })
})
