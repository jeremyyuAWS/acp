import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// ── The invariant ────────────────────────────────────────────────────────────
// Observed live 2026-07-29 on pdf-critical-untagged-no-lang.pdf: the hero card read
// "🔴 3 issues need remediation" and the badge immediately below it read "no findings",
// in the same drawer, about the same document. Two independent derivations of one fact.
//
// The document is broken by construction — scripts/gen_test_corpus.py builds it with no
// tags, no title, no /Lang and ambiguous link text, and test-corpus/manifest.json calls it
// "worst case" — so "no findings" was the false half. These tests pin that the drawer can
// never print it again while the authoritative model says otherwise.

const FAILING = {           // what derive_file_status returns for that document
  available: true, in_scope: 38, coverage: { evaluable: 15, total: 38 },
  resolved: 2, automatically_verified: 2, human_verified: 0, human_verified_criteria: [],
  needs_review: 10, needs_remediation: 3, not_automatically_assessable: 23,
  not_applicable: 0, unapplied_approved: 0, est_review_secs: 450,
  state: 'needs_remediation', cta: 'Start Remediation',
}
const CLEAR = {
  ...FAILING, needs_review: 0, needs_remediation: 0, resolved: 15,
  state: 'ready_for_certification', cta: 'Generate Report',
}

vi.mock('./api.js', () => ({
  getFileStatus: vi.fn(() => Promise.resolve(FAILING)),
  getScanStatus: vi.fn(() => Promise.resolve(FAILING)),
}))

const { statusOf, findingsClaim } = await import('./FileDrawer.jsx')
const { default: AccessibilityStatus } = await import('./AccessibilityStatus.jsx')

describe('the drawer badge and the coverage panel cannot disagree about findings', () => {
  // The exact live contradiction: statusOf() says 'clean', the server says 3 failing.
  it('never claims "no findings" while the status model reports criteria needing remediation', () => {
    const file = { file: 'pdf-critical-untagged-no-lang.pdf', status: 'analysed', compliant: 0, issues: [], score: null }
    // This unscored input used to produce 'clean' — the affirmative badge that started all of
    // this. It is now its own verdict (see statusClean.test.js), and findingsClaim reconciles
    // both: whichever verdict the row carries, the server's failing count still wins.
    expect(statusOf(file)).toBe('not-assessed')
    for (const st of ['clean', 'not-assessed']) {
      expect(findingsClaim(st, file, FAILING)).toBe('has-findings')
      expect(findingsClaim(st, file, FAILING)).not.toBe('no-findings')
    }
  })

  it('agrees with the model across every needs_remediation value', () => {
    const file = { file: 'f.pdf', status: 'analysed', compliant: 0, issues: [], score: 41 }
    for (const n of [0, 1, 2, 3, 17]) {
      const claim = findingsClaim('clean', file, { ...FAILING, needs_remediation: n })
      expect(claim === 'has-findings').toBe(n > 0)
    }
  })

  it('claims "no findings" only when the model positively reports none', () => {
    const file = { file: 'f.pdf', status: 'analysed', compliant: 0, issues: [], score: 88 }
    expect(findingsClaim('clean', file, CLEAR)).toBe('no-findings')
  })

  // 'clean' WAS statusOf's not-yet-scored bucket as much as its genuinely-clear one, and the
  // badge rendered both as the affirmative "no findings". statusOf now separates them, and the
  // claim still resolves to "not assessed" from either side.
  it('says "not yet assessed" for a never-opened Discover record, not "no findings"', () => {
    const discovered = { file: 'f.pdf', status: 'discovered', compliant: 0, issues: [], score: null }
    expect(statusOf(discovered)).toBe('not-assessed')
    expect(findingsClaim('not-assessed', discovered, null)).toBe('not-assessed')
    expect(findingsClaim('clean', discovered, null)).toBe('not-assessed')
  })

  // A file where NOTHING was auto-assessable has needs_remediation === 0 without a single
  // criterion having been verified. Reading that as "no findings" is the false-clean inference
  // again, one layer down in the model rather than in the verdict.
  it('does not read "zero failing" as "no findings" when nothing was verified', () => {
    const unscored = { file: 'f.pdf', status: 'discovered', compliant: 0, issues: [], score: null }
    const nothingRan = { available: true, in_scope: 38, needs_remediation: 0,
                         automatically_verified: 0, human_verified: 0,
                         not_automatically_assessable: 38 }
    expect(findingsClaim('not-assessed', unscored, nothingRan)).toBe('not-assessed')
    // A scored file with the same model DID get measured, so "no findings" is supportable.
    expect(findingsClaim('clean', { ...unscored, score: 100 }, nothingRan)).toBe('no-findings')
  })

  it('does not fall back to a reassuring claim when the status lookup is unavailable', () => {
    const unscored = { file: 'f.pdf', status: 'analysed', compliant: 0, issues: [], score: null }
    expect(findingsClaim('clean', unscored, { available: false })).toBe('not-assessed')
  })

  it('makes no findings claim at all for a status other than clean', () => {
    const withIssues = { file: 'f.pdf', status: 'analysed', compliant: 0, issues: [{ wcag: '1.1.1' }], score: 40 }
    expect(statusOf(withIssues)).toBe('issues')
    expect(findingsClaim('issues', withIssues, FAILING)).toBe(null)
  })
})

let container, root
beforeEach(() => {
  ;({ container, root } = createTestRoot())
})
// Same reason as inventoryAgreesWithDrawer.test.jsx: AccessibilityStatus resolves getFileStatus
// and calls setM, so a root left mounted keeps work in React's concurrent scheduler past the last
// assertion, where an environment teardown turns it into an unhandled `window is not defined`.
// This file has the same shape and the same latent exposure; it simply has not lost the race yet.
afterEach(unmountAll)
const render = async (props) => { await act(async () => { root.render(createElement(AccessibilityStatus, props)) }) }

// The invariant only holds if the drawer actually receives the card's model, so pin the wiring.
describe('AccessibilityStatus reports its model up so the drawer reuses it', () => {
  it('hands the fetched model to onModel', async () => {
    const seen = []
    await render({ scanId: 's1', file: 'pdf-critical-untagged-no-lang.pdf', onModel: (m) => seen.push(m) })
    expect(seen).toContainEqual(FAILING)
    // What the drawer derives from it contradicts nothing the card rendered.
    expect(findingsClaim('clean', { status: 'analysed', score: null }, seen[seen.length - 1])).toBe('has-findings')
  })

  it('clears the previous file’s model before the next lookup resolves', async () => {
    const seen = []
    await render({ scanId: 's1', file: 'a.pdf', onModel: (m) => seen.push(m) })
    expect(seen[0]).toBe(null)          // no stale model can outlive a file switch
    expect(seen[seen.length - 1]).toEqual(FAILING)
  })

  it('the card and the badge tell the same story on screen', async () => {
    await render({ scanId: 's1', file: 'pdf-critical-untagged-no-lang.pdf', onModel: () => {} })
    expect(container.textContent).toContain('3 issues need remediation')
    expect(container.textContent).not.toContain('no findings')
  })
})

// ── Pluralisation (item 3) ───────────────────────────────────────────────────
describe('criterion/criteria', () => {
  it('never renders the concatenated "criteriona"', async () => {
    await render({ scanId: 's1', file: 'f.pdf' })
    expect(container.textContent).not.toMatch(/criteriona/)
    expect(container.textContent).toContain('3 criteria are failing and need a fix')
  })

  it('uses the singular stem, and singular agreement, for exactly one', async () => {
    const { getFileStatus } = await import('./api.js')
    getFileStatus.mockResolvedValueOnce({ ...FAILING, needs_remediation: 1 })
    await render({ scanId: 's1', file: 'one.pdf' })
    expect(container.textContent).toContain('1 criterion is failing and needs a fix')
    expect(container.textContent).not.toMatch(/criteriona|criterions/)
  })

  it('pluralises the review sentence without concatenating a suffix', async () => {
    const { getFileStatus } = await import('./api.js')
    getFileStatus.mockResolvedValueOnce({
      ...CLEAR, needs_review: 4, state: 'ready_after_review', resolved: 2,
    })
    await render({ scanId: 's1', file: 'rev.pdf' })
    expect(container.textContent).toContain('4 criteria still require human verification')
    expect(container.textContent).not.toMatch(/criteriona/)
  })
})

// ── The wiring ───────────────────────────────────────────────────────────────
// findingsClaim() being correct is worth nothing if the drawer stops feeding it the model or
// goes back to rendering `st === 'clean'` directly, and neither shows up in a unit test of the
// pure function. Guard the render path at the source, the way statusClean.test.js does.
describe('the drawer renders through the reconciled claim, not a second derivation', () => {
  const drawerSrc = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'FileDrawer.jsx'), 'utf8')

  it('feeds the hero card’s model back into the drawer', () => {
    expect(drawerSrc).toMatch(/<AccessibilityStatus[^>]*onModel=\{setStatusModel\}/)
    expect(drawerSrc).toMatch(/const claim = findingsClaim\(st, file, statusModel\)/)
  })

  it('gates every findings sentence on the claim rather than on st === \'clean\'', () => {
    // The three mutually-exclusive sentences are claim-gated …
    expect(drawerSrc).toMatch(/\{claim === 'no-findings' && <span className="muted">no blocking findings/)
    expect(drawerSrc).toMatch(/\{claim === 'not-assessed' && <span className="muted">not yet assessed/)
    expect(drawerSrc).toMatch(/\{claim === 'has-findings' && <span className="muted">/)
    // … and the bare `st === 'clean' && <span …>no blocking findings` form is gone.
    expect(drawerSrc).not.toMatch(/\{st === 'clean' && <span className="muted">no blocking findings/)
  })

  it('colours the badge for what it can assert', () => {
    expect(drawerSrc).toMatch(/STATUS_BADGE\[claim === 'has-findings' \? 'issues' : st\]/)
  })
})

// ── The replay banner (item 2) ───────────────────────────────────────────────
describe('time-travel means a past scan, and always has a date', () => {
  const appSrc = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'App.jsx'), 'utf8')

  // The predicate, transcribed — a run absent from scanList (still in flight, or an ADR 0020
  // Discover-only run) is not a replay, and is exactly the case that rendered an empty date.
  const isTimeTravel = (run, scanList) =>
    !!(run && scanList.some((s) => s.id === run.id) && scanList[0]?.id !== run.id)

  const older = { id: 'a', completed_at: '2026-07-20T10:00:00Z' }
  const newest = { id: 'b', completed_at: '2026-07-29T10:00:00Z' }
  const list = [newest, older]

  it('is true for a genuinely past scan', () => {
    expect(isTimeTravel(older, list)).toBe(true)
  })
  it('is false for the newest scan', () => {
    expect(isTimeTravel(newest, list)).toBe(false)
  })
  it('is false for an in-flight run that listScans() omits', () => {
    // The reported symptom: no completed_at, so the banner printed "from ." — and readOnly
    // came on across Remediate/Publish/Monitor for what is actually the newest scan.
    const running = { id: 'c', completed_at: null }
    expect(isTimeTravel(running, list)).toBe(false)
  })
  it('is false for a Discover-only run awaiting Assess', () => {
    expect(isTimeTravel({ id: 'd', status: 'discovered', completed_at: null }, list)).toBe(false)
  })
  it('is false when there is no scan list yet', () => {
    expect(isTimeTravel(newest, [])).toBe(false)
  })

  it('keeps a fallback so a null stamp can never render as a bare period', () => {
    expect(appSrc).toMatch(/fmtStamp\(run\.completed_at\) \?\? 'an earlier scan'/)
    expect(appSrc).toMatch(/scanList\.some\(\(s\) => s\.id === run\.id\)/)
  })
})

// ── Panel title layout (item 4) ──────────────────────────────────────────────
describe('the coverage panel heading holds its own line', () => {
  const drawerSrc = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'FileDrawer.jsx'), 'utf8')
  const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'styles.css'), 'utf8')

  it('wraps the title so it is not an anonymous flex item beside the count chips', () => {
    // The wrapper is what this pins, not the wording — the title now names the active scope, so
    // asserting the old copy would fail on a label change that has nothing to do with the layout
    // bug. What must not come back is a BARE TEXT NODE in the summary: as an anonymous flex item
    // beside nine chips it shrank to its minimum content width and rendered one word per line.
    expect(drawerSrc).toMatch(/<span className="covmanifest-title"[^>]*>WCAG coverage · [^<]+<\/span>/)
    // Scoped to the summary that actually carries the chips. A blanket "no bare text node in any
    // covmanifest-sum" would also condemn the unanalysable-file variant, which has no chips beside
    // it and therefore never had the bug.
    expect(drawerSrc).toMatch(/<summary className="covmanifest-sum">[\s\S]{0,400}?<span className="covmanifest-title"[\s\S]{0,200}?\{chip\('PASS'/)
  })
  it('gives the title column a min-width and lets the chips wrap', () => {
    expect(css).toMatch(/\.covmanifest-title \{[^}]*min-width:/)
    expect(css).toMatch(/\.covmanifest summary \{[^}]*flex-wrap: wrap/)
  })

  // The actual cause: `.covstat` is declared twice for two unrelated components. The WCAG
  // coverage matrix (WcagCoverage.jsx) uses it as a stat-card GRID with a 160px minimum
  // track; the drawer reuses the name for its count pills and never set `display`, so each
  // pill inherited that grid and claimed >= 160px. Nine of them left the heading no room.
  // Measured at a 380px drawer: pills 178px wide and the title 0px / 7 lines before,
  // content-width pills and a single-line title after.
  it('scopes the count pills so they cannot inherit the coverage-matrix grid', () => {
    expect(css).toMatch(/\.covmanifest-sum \.covstat \{[^}]*display: inline-block/)
    // The grid rule that collided must still belong to the matrix, unscoped and intact.
    expect(css).toMatch(/^\.covstat \{[^}]*display: grid/m)
    // …and the pill rule must no longer be a bare `.covstat`, or the collision returns.
    expect(css).not.toMatch(/^\.covstat \{[^}]*border-radius: 999px/m)
  })

  it('leaves the WcagCoverage stat-card grid alone', () => {
    // If someone "fixes" this by overriding display on the unscoped selector instead, the
    // matrix's card grid silently becomes inline-block. Pin that it stays a grid.
    const gridRule = css.match(/^\.covstat \{[^}]*\}/m)[0]
    expect(gridRule).toContain('display: grid')
    expect(gridRule).toContain('minmax(160px, 1fr)')
  })
})

// ── Denominator labelling (item 5) ───────────────────────────────────────────
describe('the coverage denominator says what it counts', () => {
  it('labels 15 / 38 rather than leaving the totals unexplained', async () => {
    await render({ scanId: 's1', file: 'f.pdf' })
    expect(container.textContent).toContain('15 / 38')
    expect(container.textContent).toContain('criteria ACP had a method for, of 38 traced')
  })
})
