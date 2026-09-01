import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// The rendered gate. runIntegrity.test.js asserts the VERDICT; this asserts that the verdict
// actually reaches the reader — including in the states where the temptation is to render nothing.
//
// The four scenarios are the four ways a run can mislead someone reading it:
//   incomplete   checks that never ran, counted as passes
//   engine error a file nothing opened, presented as assessed
//   stale        the previous run's numbers under this run's heading
//   complete     the gate must be able to clear a run, or it is a permanent warning nobody reads

let mockManifest
let mockError
vi.mock('./api.js', () => ({
  getScanManifest: () => (mockError ? Promise.reject(mockError) : Promise.resolve(mockManifest)),
}))

const { default: AssessRunIntegrity } = await import('./AssessRunIntegrity.jsx')

const file = (over = {}) => ({
  file: 'a.docx', file_status: 'analysed', reason: null,
  rules_expected: 17, rules_checked: 17, rules_errored: 0, rules_not_checked: 0,
  rules_errored_unattributed: 0, rules_not_applicable: 53,
  completeness_pct: 100, complete: true, rules: [], ...over,
})

const COMPLETE_MANIFEST = {
  scan_id: 'run-1', files_total: 2,
  rules_expected_total: 34, rules_checked_total: 34, rules_errored_total: 0,
  rules_not_checked_total: 0, rules_errored_unattributed_total: 0,
  rules_not_applicable_total: 106, completeness_pct: 100, complete: true,
  files: [file(), file({ file: 'b.docx' })],
}

const BROKEN_MANIFEST = {
  ...COMPLETE_MANIFEST,
  rules_checked_total: 17, rules_not_checked_total: 17, completeness_pct: 50, complete: false,
  files: [file(), file({
    file: 'broken.docx', file_status: 'error', rules_checked: 0, rules_not_checked: 17,
    completeness_pct: 0, complete: false,
    rules: [{ rule_id: 'DOCX-ALT-001', status: 'NOT_CHECKED', finding_count: 0 },
            { rule_id: 'DOCX-TITLE-001', status: 'NOT_CHECKED', finding_count: 0 },
            { rule_id: 'DOCX-LANG-001', status: 'NOT_APPLICABLE', finding_count: 0 }],
  })],
}

const mount = async (props = {}) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(AssessRunIntegrity, { scanId: 'run-1', ...props }))
  })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return container
}

beforeEach(() => { mockManifest = COMPLETE_MANIFEST; mockError = null })
afterEach(unmountAll)

// ── a fully complete scan ─────────────────────────────────────────────────────────────────
describe('a run where every applicable check ran', () => {
  it('says so, and reports checked against expected', async () => {
    const t = (await mount()).textContent
    expect(t).toContain('Every applicable check ran')
    expect(t).toMatch(/34\s*of\s*34 applicable checks completed/)
    expect(t).toContain('100%')
  })

  it('lists no affected files', async () => {
    expect((await mount()).textContent).not.toContain('Affected files')
  })

  it('still counts the four outcomes separately rather than as one score', async () => {
    // The collapse this panel exists to prevent: "passed" and "not checked" summed into a
    // single reassuring number.
    const t = (await mount()).textContent
    for (const label of ['Passed', 'Not checked', 'Errored', 'Not applicable']) {
      expect(t).toContain(label)
    }
    expect(t).toContain('106')          // the not-applicable count is shown, not hidden
  })
})

// ── an incomplete scan ────────────────────────────────────────────────────────────────────
describe('a run with checks that did not run', () => {
  beforeEach(() => { mockManifest = BROKEN_MANIFEST })

  it('refuses the conformance claim in words, at the top', async () => {
    const t = (await mount()).textContent
    expect(t).toMatch(/not a conformance result/i)
  })

  it('shows the completeness percentage and the shortfall', async () => {
    const t = (await mount()).textContent
    expect(t).toMatch(/17\s*of\s*34 applicable checks completed/)
    expect(t).toContain('50%')
  })

  it('separates the checks that did not run from the ones that passed', async () => {
    const c = await mount()
    const rows = [...c.querySelectorAll('tbody tr')].map((r) => r.textContent)
    expect(rows.find((r) => r.startsWith('Passed'))).toMatch(/17/)
    expect(rows.find((r) => r.startsWith('Not checked'))).toMatch(/17/)
    // The sentence that keeps them apart travels with the number.
    expect(rows.find((r) => r.startsWith('Not checked'))).toMatch(/not a pass/i)
  })

  it('names the affected files', async () => {
    const t = (await mount()).textContent
    expect(t).toContain('Affected files (1)')
    expect(t).toContain('broken.docx')
    expect(t).not.toMatch(/Affected files[\s\S]*a\.docx/)
  })

  it('names the individual checks that did not run, and no not-applicable ones', async () => {
    const c = await mount()
    const details = c.querySelector('details')
    expect(details.textContent).toContain('DOCX-ALT-001')
    expect(details.textContent).toContain('DOCX-TITLE-001')
    // Not a gap — it was never owed.
    expect(details.textContent).not.toContain('DOCX-LANG-001')
  })

  it('renders the arithmetic so a partition that stops summing is visible', async () => {
    expect((await mount()).textContent).toMatch(/17 passed \+ 0 errored \+ 17 not checked = 34 applicable/)
  })

  it('warns in the arithmetic line when the numbers do not add up', async () => {
    mockManifest = { ...BROKEN_MANIFEST, rules_checked_total: 5 }
    expect((await mount()).textContent).toMatch(/do not add up/i)
  })
})

// ── engine failures ───────────────────────────────────────────────────────────────────────
describe('a run where the engine failed', () => {
  it('explains a file it could not open, rather than only counting it', async () => {
    mockManifest = BROKEN_MANIFEST
    expect((await mount()).textContent).toContain('The engine could not analyse this file.')
  })

  it('shows an errored check apart from one that never ran', async () => {
    mockManifest = {
      ...COMPLETE_MANIFEST, complete: false,
      rules_checked_total: 31, rules_errored_total: 2, rules_not_checked_total: 1,
      files: [file(), file({ file: 'partial.docx', rules_checked: 14, rules_errored: 2,
                             rules_not_checked: 1, complete: false })],
    }
    const rows = [...(await mount()).querySelectorAll('tbody tr')].map((r) => r.textContent)
    expect(rows.find((r) => r.startsWith('Errored'))).toMatch(/2/)
    expect(rows.find((r) => r.startsWith('Not checked'))).toMatch(/1/)
  })

  it('reports errors the engine could not attribute to a named check', async () => {
    mockManifest = {
      ...COMPLETE_MANIFEST, complete: false,
      rules_checked_total: 32, rules_errored_unattributed_total: 2,
      files: [file(), file({ file: 'legacy.docx', rules_checked: 15,
                             rules_errored_unattributed: 2, complete: false })],
    }
    const t = (await mount()).textContent
    expect(t).toContain('Errored (unidentified)')
    expect(t).toMatch(/did not record which checks/i)
  })

  it('does not show the unidentified row when there are none, to keep the table quiet', async () => {
    expect((await mount()).textContent).not.toContain('Errored (unidentified)')
  })
})

// ── stale results during a new run ────────────────────────────────────────────────────────
describe('results still on screen while a new run is going', () => {
  it('says they describe an earlier run', async () => {
    const t = (await mount({ runInFlight: true })).textContent
    expect(t).toContain('These results describe an earlier run')
  })

  it('withholds the counts entirely rather than labelling last run’s as this run’s', async () => {
    // The hard part: the manifest is internally perfect and describes a finished, fully-covered
    // run. There is nothing in the payload to notice, so the numbers must not be shown at all.
    const c = await mount({ runInFlight: true })
    expect(c.querySelector('tbody')).toBeNull()
    expect(c.textContent).not.toContain('34 of 34')
    expect(c.textContent).not.toContain('100%')
  })

  it('catches a manifest whose scan is not the one on screen, with no run in flight', async () => {
    // Survives a reload, where an "is something running" flag does not.
    const t = (await mount({ scanId: 'run-1', currentScanId: 'run-2' })).textContent
    expect(t).toContain('These results describe an earlier run')
    expect(t).toMatch(/different run/i)
  })

  it('clears once the new run’s own manifest arrives', async () => {
    mockManifest = { ...COMPLETE_MANIFEST, scan_id: 'run-2' }
    const t = (await mount({ scanId: 'run-2', runInFlight: false })).textContent
    expect(t).toContain('Every applicable check ran')
  })
})

// ── the manifest could not be read ────────────────────────────────────────────────────────
describe('when the coverage record cannot be read', () => {
  it('renders the panel anyway, saying coverage is unknown', async () => {
    // A panel that vanishes when it cannot answer leaves the summary below it looking
    // unqualified — the exact outcome the gate exists to prevent.
    mockError = new Error('network down')
    const t = (await mount()).textContent
    expect(t).toContain('Run coverage could not be read')
    expect(t).toContain('network down')
  })

  it('does not present unknown coverage as a conformance result', async () => {
    mockError = new Error('network down')
    const t = (await mount()).textContent
    expect(t).toMatch(/cannot be presented as a conformance result/i)
    expect(t).not.toContain('Every applicable check ran')
  })

  it('says the findings on screen are still real, so it is not read as data loss', async () => {
    mockError = new Error('x')
    expect((await mount()).textContent).toMatch(/findings below are still/i)
  })
})

// ── the panel itself ──────────────────────────────────────────────────────────────────────
describe('the panel', () => {
  it('announces its verdict to assistive technology', async () => {
    const c = await mount()
    expect(c.querySelector('[role="status"]').textContent).toContain('Every applicable check ran')
  })

  it('is labelled and headed, so it is reachable by landmark', async () => {
    const c = await mount()
    const section = c.querySelector('section[aria-labelledby]')
    expect(section).not.toBeNull()
    expect(c.querySelector(`#${section.getAttribute('aria-labelledby')}`).textContent)
      .toBe('Run integrity')
  })

  it('names the outcome table with a caption that is hidden by a class this app defines', async () => {
    // `sr-only` is a common convention and NOT one of this codebase's; styles.css defines
    // `.sronly` and `.vh`. A caption under the wrong class is visible stray text.
    const c = await mount()
    const caption = c.querySelector('table caption')
    expect(caption.textContent).toContain('Check outcomes for this run')
    expect(caption.className).toBe('sronly')
  })

  it('gives the outcome table real row and column headers', async () => {
    mockManifest = BROKEN_MANIFEST
    const c = await mount()
    expect([...c.querySelectorAll('thead th')].map((h) => h.textContent))
      .toEqual(['Outcome', 'Checks', 'What it means'])
    expect(c.querySelector('tbody th').getAttribute('scope')).toBe('row')
  })

  it('cannot be collapsed away — the caveat has to be in the screenshot', async () => {
    mockManifest = BROKEN_MANIFEST
    const c = await mount()
    // The only disclosure is the per-file rule list, never the verdict itself.
    const summaries = [...c.querySelectorAll('summary')].map((s) => s.textContent)
    expect(summaries.every((s) => s.startsWith('Which checks'))).toBe(true)
    expect(c.querySelector('[role="status"]')).not.toBeNull()
  })

  it('accepts a manifest directly, so a caller that already has one does not refetch', async () => {
    mockManifest = null            // the fetch would produce nothing
    const t = (await mount({ manifest: BROKEN_MANIFEST })).textContent
    expect(t).toMatch(/not a conformance result/i)
  })
})
