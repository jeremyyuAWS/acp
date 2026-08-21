/**
 * The scan-launch scope WIZARD (Phase 1): the short "start scan" decision that replaces the dense
 * admin grid as the first thing an operator sees, keeping the grid behind a "Customize" reveal.
 *
 * Two kinds of test here:
 *   - DOM-level, mounting the component: the profile pills, the format cards, the summary line, the
 *     reveal wrapping the grid, and — the load-bearing one — that each format card's count is the
 *     number of tracked criteria the engine can reach a verdict on for that format, DERIVED from
 *     SCOPE_UNIVERSE the same way the component derives it, never a retyped list.
 *   - Source-level and COMMENT-STRIPPED (mirroring driveArchive.test.js): that Integrations mounts
 *     the wizard and routes "Scan all sources" through the required modal. Integrations is deep in
 *     OAuth/MSAL wiring that a unit mount would have to stub wholesale, so its integration is
 *     asserted against code lines, and a naive substring match would also hit this very comment —
 *     so those assertions run against non-comment lines only.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in, so a browser check of a worktree change exercises code that does
 * not contain it (see CLAUDE.md).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import { gotoStep } from './wizardNav.testkit.js'

afterEach(unmountAll)

const settingsMock = { get: null, put: null }
vi.mock('./api.js', () => ({
  getSettings: (...a) => settingsMock.get(...a),
  updateSettings: (...a) => settingsMock.put(...a),
  // The review step names how many lifecycle rules will run during the discovery.
  listDispositionPolicies: vi.fn(async () => []),
}))

const { default: ScanScopeWizard } = await import('./ScanScopeWizard.jsx')
const { SCOPE_UNIVERSE, SCOPE_FORMATS } = await import('./scopePresets.js')
const { TRACKED_17 } = await import('./ruleDetails.js')
const { ASSESSMENT_FALLBACK, assessmentFor } = await import('./capability.js')

// Derived exactly as the component derives them — the universe narrowed to the tracked criteria,
// then split into what ACP can actually ASSESS (`ready`, the selectable/counted cells) vs what the
// engine merely reaches. A cell is ready when its assessment lane is 'auto' or 'review' (both
// return a verdict); 'human'/absent do not, so they are greyed and can't be selected.
const isReady = (sc, f) => ['auto', 'review'].includes(assessmentFor(ASSESSMENT_FALLBACK, f, sc))
const OFFERED = SCOPE_UNIVERSE
  .filter((r) => TRACKED_17.has(r.sc))
  .map((r) => ({ ...r, ready: r.formats.filter((f) => isReady(r.sc, f)) }))
// The count each format card shows: tracked criteria ACP can assess for that format (ready only).
const FMT_COUNT = Object.fromEntries(
  SCOPE_FORMATS.map((f) => [f, OFFERED.filter((r) => r.ready.includes(f)).length]),
)
const FMT_LABEL = { docx: 'DOCX', xlsx: 'XLSX', pptx: 'PPTX', pdf: 'PDF' }

async function render(props = {}, stored = '') {
  settingsMock.get = vi.fn(async () => ({ scan_scope: stored }))
  settingsMock.put = vi.fn(async (patch) => ({ scan_scope: typeof patch.scan_scope === 'string'
    ? patch.scan_scope : JSON.stringify(patch.scan_scope) }))
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ScanScopeWizard, props)) })
  return container
}

const byRole = (c, role) => [...c.querySelectorAll(`[role="${role}"]`)]
const cardByLabel = (c, label) => [...c.querySelectorAll('[role="checkbox"],[role="radio"],button')]
  .find((e) => (e.getAttribute('aria-label') || '').includes(label))
const click = async (el) => { await act(async () => { el.click() }) }

// ── the four choices, the four cards, the summary ──────────────────────────────────────────────
describe('the wizard chrome', () => {
  it('uses the new wording, not the old "pairs" phrasing', async () => {
    const c = await render()
    // THE OLD LINE IS GONE, and it deserved to be. It read "the same scope will be used for
    // assessment, remediation, reporting, and export" — describing a criteria scope this screen
    // stopped choosing in #532. A sentence that outlives the thing it described is worse than no
    // sentence: it is a wrong answer in the position a reader trusts most.
    expect(c.textContent).toMatch(/Choose where ACP should inventory/)
    expect(c.textContent, 'the wizard still promises to reuse this scope for assessment')
      .not.toMatch(/same scope will be used for assessment/)
    expect(c.textContent).not.toMatch(/of \d+ pairs selected/)
  })
})

// ── the load-bearing one: card counts are derived, not typed ────────────────────────────────────
// ── the Customize reveal wraps the existing grid ────────────────────────────────────────────────
// ── owning its own state: picking a profile loads it ────────────────────────────────────────────
describe('scope state', () => {
  it('renders the footer with showStartButton, and starts discovery on confirm', async () => {
    // Same guarantee as always — the footer exists and confirming dispatches onStartScan — but
    // it is reached by walking three steps again.
    //
    // THIS CASE USED TO ASSERT THE OPPOSITE, in these words: "there is nothing to walk through
    // now. One question, one screen, one action", with a check that no Continue control had
    // survived the collapse. That was right while Discover had one decision in it. It has three
    // (where to inventory, which lifecycle rules run, and the review that carries the
    // metadata-only promise), so a Continue control is now required rather than forbidden — and
    // the inversion is written down rather than quietly dropped.
    const started = vi.fn()
    const c = await render({ showStartButton: true, onStartScan: started })
    expect([...c.querySelectorAll('button')].some((b) => /Continue to rules/.test(b.textContent)),
      'step 1 has no forward control').toBe(true)
    await gotoStep(c, act, 3)
    const startBtn = c.querySelector('button[data-wizard-forward]')
    expect(startBtn, 'no run control on the review step').toBeTruthy()
    // "discovery", not "scan": this lists the estate and opens no file — the WCAG work is Assess's.
    expect(startBtn.textContent).toMatch(/Run discovery/)
    expect(c.textContent).not.toMatch(/Start scan/)
    await click(startBtn)
    expect(started).toHaveBeenCalled()
  })

  it('offers NO format or WCAG control — the phase-1 exit condition', async () => {
    // Was "shows one step at a time, so the matrix is not in front of a first-time user", when
    // this was a layout preference. It is a rule now (PRD DISC-01), so the assertion is inverted
    // and kept: Discover asks where to inventory and nothing else. The formats and criteria live
    // in Assess, against the inventory this produces.
    const c = await render({ showStartButton: true })
    expect(c.textContent).toMatch(/DRIVE LOCATIONS|Entire connected source/)
    for (const gone of [/FILE FORMATS/, /SCAN PROFILE/, /supported checks selected/,
                        /Customize/, /Not supported/]) {
      expect(c.textContent, `a format/criteria control is back on Discover: ${gone}`)
        .not.toMatch(gone)
    }
    // The absence must hold on EVERY step, not just the one the wizard opens on — a criteria grid
    // reintroduced behind step 2 or 3 would sail past a check that only ever looked at step 1.
    await gotoStep(c, act, 3)
    for (const gone of [/FILE FORMATS/, /SCAN PROFILE/, /supported checks selected/]) {
      expect(c.textContent, `a format/criteria control is back on a later step: ${gone}`)
        .not.toMatch(gone)
    }
    // And the review says what the run WILL cover, so "no format control" cannot be read as
    // "no formats". That line lives on step 3 now, which is why this walks there.
    expect(c.textContent).toMatch(/All file types will be inventoried/)
  })

})

// ── owner-only: a non-owner (canEditScope=false) gets a read-only wizard + a clear note ──────────
// ── Phase 2: the redesigned matrix (sticky, principle groups, column/row/group controls, cells,
//    search + filters) ─────────────────────────────────────────────────────────────────────────
const detailsOf = (c) => [...c.querySelectorAll('details')]
  .find((d) => /View or customize criteria/.test(d.querySelector('summary')?.textContent || ''))
const gridOf = (c) => detailsOf(c).querySelector('table')
// A control the redesign renders as a role=checkbox button (group / column / row toggles, filters),
// found by its aria-label — distinct from the cell inputs, which are input[type=checkbox].
const toggleByLabel = (scope, re) => byRole(scope, 'checkbox')
  .filter((e) => e.tagName === 'BUTTON')
  .find((e) => re.test(e.getAttribute('aria-label') || ''))
const cellBoxes = (c) => [...gridOf(c).querySelectorAll('input[type=checkbox]')]
const checkedCount = (c) => cellBoxes(c).filter((b) => b.checked).length
// The grid renders the live `sel` map, which is empty under "Everything supported"; pick Core 17
// (the whole offered grid, restrict on) so every supported cell reads as ticked to start.
const pickCore17 = async (c) => {
  const core = byRole(c, 'radio').find((r) => r.textContent.includes('Core 17'))
  await click(core)
}
// Type into a controlled React input via the native value setter, so React's onChange fires.
const typeSearch = async (input, value) => {
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => {
    set.call(input, value)
    input.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
}

// ── readiness: cells ACP can't assess yet are greyed, disabled, and out of the count ────────────
// ── source-level: the shared ScanReviewModal mounts the wizard, and App gates every scan ────────
// The review modal moved OUT of Integrations to app level (ScanReviewModal.jsx, rendered once by
// App) so every entry point — not just the Sources tab — passes through it. These assert that
// wiring against code lines (Integrations is deep in OAuth/MSAL that a unit mount would stub
// wholesale). Comment lines are stripped first, so a naive substring can't match this very block.
const HERE = dirname(fileURLToPath(import.meta.url))
const codeOf = (f) => readFileSync(join(HERE, f), 'utf8')
  .split('\n')
  .filter((l) => {
    const t = l.trim()
    return !t.startsWith('//') && !t.startsWith('/*') && !t.startsWith('*') && !t.startsWith('{/*')
  })
  .join('\n')

describe('the shared ScanReviewModal mounts the wizard', () => {
  const code = codeOf('ScanReviewModal.jsx')

  it('imports and mounts the wizard with a Start button and a scan callback', () => {
    expect(code).toMatch(/import ScanScopeWizard from '\.\/ScanScopeWizard\.jsx'/)
    expect(code).toMatch(/<ScanScopeWizard showStartButton/)
    expect(code).toMatch(/onStartScan=\{[^}]*onConfirm/)
  })

  it('is a real dialog ~1.5× wider than the old Sources-tab modal', () => {
    expect(code).toMatch(/role="dialog"[\s\S]*aria-modal="true"/)
    expect(code).toMatch(/min\(940px, 100%\)/)
  })
})

describe('App renders the gate once and routes every entry point through it', () => {
  const code = codeOf('App.jsx')

  it('opens the gate via requestScan instead of scanning inline', () => {
    expect(code).toMatch(/const requestScan = \(source, folder = null\) => setPendingScan/)
    expect(code).toMatch(/<ScanReviewModal/)
    // The confirm is the only path that dispatches doScan. It now also carries the wizard's
    // per-run folder scope as a third argument — the intent (one dispatch path) is unchanged.
    expect(code).toMatch(/onConfirm=\{[\s\S]*?doScan\(source, folder, runScope\)/)
  })

  it('wires onScan={requestScan} at every entry point, not doScan', () => {
    // REWRITTEN — the loop this replaces asserted `expect('<EmptyState').toBeTruthy()`, i.e. that
    // a string literal is truthy. It passed for every possible state of the app, including one
    // where every entry point was wired straight to doScan. The count beside it (>= 4) was the
    // only real assertion, and a count is exactly what a legitimate change breaks: EmptyState
    // stopped being a scan entry point entirely when it became the Go-to-Source screen.
    //
    // So assert the thing itself — each component that STILL launches a scan carries
    // onScan={requestScan} — and that EmptyState no longer does.
    for (const entry of ['Overview', 'Integrations', 'Discover']) {
      const tag = new RegExp(`<${entry}\\b[^>]*onScan=\\{requestScan\\}`, 's')
      expect(code, `${entry} does not route its scan through the gate`).toMatch(tag)
    }
    expect(code, 'EmptyState is a scan entry point again').not.toMatch(/<EmptyState[^>]*onScan=/s)
    expect(code).not.toMatch(/onScan=\{doScan\}/)
  })
})

describe('Integrations no longer owns the modal', () => {
  const code = codeOf('Integrations.jsx')

  it('does not import or mount the wizard, and renders no dialog', () => {
    expect(code).not.toMatch(/ScanScopeWizard/)
    expect(code).not.toMatch(/role="dialog"/)
    expect(code).not.toMatch(/setScanModalOpen/)
  })

  it('its New scan buttons just call onScan', () => {
    expect(code).toMatch(/onScan\('all'\)/)
    expect(code).toMatch(/onScan\(cardScanArg\(src\)\)/)
  })
})

describe('the Drive/SharePoint browse panels gate through Upload (parity-safe)', () => {
  it('Upload opens the shared modal before assessing browse selections', () => {
    const code = codeOf('Upload.jsx')
    expect(code).toMatch(/import ScanReviewModal from '\.\/ScanReviewModal\.jsx'/)
    // The browse handlers open the gate instead of assessing inline…
    expect(code).toMatch(/setBrowseGate\(\{ source: 'drive'/)
    expect(code).toMatch(/setBrowseGate\(\{ source: 'sharepoint'/)
    // …and only the modal's confirm runs the assess path.
    expect(code).toMatch(/onConfirm=\{[\s\S]*?processBrowseFiles\(g\.files\)/)
  })

  it('the browse panels themselves carry no modal — GoogleDrive.jsx stays byte-identical', () => {
    // The gate lives in the shared parent (Upload), NOT in GoogleDrive.jsx, which driveArchive
    // .test.js pins byte-for-byte to the legacy SPA. Guard that here so a future refactor that
    // "helpfully" moves the modal into the panel is caught with this reason attached.
    expect(codeOf('GoogleDrive.jsx')).not.toMatch(/ScanReviewModal/)
    expect(codeOf('SharePoint.jsx')).not.toMatch(/ScanReviewModal/)
  })
})
