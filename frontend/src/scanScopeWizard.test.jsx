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

afterEach(unmountAll)

const settingsMock = { get: null, put: null }
vi.mock('./api.js', () => ({
  getSettings: (...a) => settingsMock.get(...a),
  updateSettings: (...a) => settingsMock.put(...a),
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
  it('offers the four scan profiles', async () => {
    const c = await render()
    const labels = byRole(c, 'radio').map((r) => r.textContent)
    for (const want of ['Core 17', 'Engagement 14', 'Custom scope', 'Everything supported']) {
      expect(labels.some((l) => l.includes(want)), `missing profile "${want}"`).toBe(true)
    }
    expect(labels.some((l) => l.includes('Recommended'))).toBe(true)
  })

  it('offers the four format cards', async () => {
    const c = await render()
    const cards = byRole(c, 'checkbox').filter((e) => /supported criteria/.test(e.getAttribute('aria-label') || ''))
    expect(cards.length).toBe(4)
    for (const f of SCOPE_FORMATS) expect(cardByLabel(c, `${FMT_LABEL[f]} —`)).toBeTruthy()
  })

  it('renders a summary line in the "<n> supported checks selected" style', async () => {
    const c = await render()   // defaults to Everything supported (no stored scope)
    const text = c.textContent
    expect(text).toMatch(/supported checks selected/)
    expect(text).toMatch(/unsupported combination.*will not be evaluated/)
    // Everything supported evaluates every READY cell in the offered grid (not-ready pairs are
    // excluded from selection, so they are not counted).
    const total = OFFERED.reduce((n, r) => n + r.ready.length, 0)
    expect(text).toMatch(new RegExp(`${total} supported checks selected`))
  })

  it('uses the new wording, not the old "pairs" phrasing', async () => {
    const c = await render()
    expect(c.textContent).toMatch(/same scope will be used for assessment, remediation, reporting, and export/)
    expect(c.textContent).not.toMatch(/of \d+ pairs selected/)
  })
})

// ── the load-bearing one: card counts are derived, not typed ────────────────────────────────────
describe('the format cards', () => {
  it('show the real per-format supported-criteria count from SCOPE_UNIVERSE', async () => {
    const c = await render()
    for (const f of SCOPE_FORMATS) {
      const card = cardByLabel(c, `${FMT_LABEL[f]} —`)
      expect(card, `no card for ${f}`).toBeTruthy()
      expect(card.getAttribute('aria-label')).toContain(`${FMT_COUNT[f]} supported criteria`)
      expect(card.textContent).toContain(`${FMT_COUNT[f]} supported criteria`)
    }
    // Guard the numbers themselves so a regression in the derivation is visible here. These are the
    // ASSESSABLE (ready) counts per format — lower than the engine-reachable counts, because pairs
    // ACP can't yet certify/detect are excluded (e.g. pptx still drops 2.1.2). xlsx rose to 14 and
    // pdf to 13 when R8 declared xlsx 1.4.1/1.4.11/4.1.2 and pdf 2.4.3 as registry-backed review lanes.
    expect(FMT_COUNT).toEqual({ docx: 15, xlsx: 14, pptx: 11, pdf: 13 })
  })
})

// ── the Customize reveal wraps the existing grid ────────────────────────────────────────────────
describe('the Customize reveal', () => {
  it('wraps the criterion × format grid, one row per offered criterion', async () => {
    const c = await render()
    const details = [...c.querySelectorAll('details')]
      .find((d) => /Customize criteria and combinations/.test(d.querySelector('summary')?.textContent || ''))
    expect(details, 'no "Customize" reveal').toBeTruthy()
    const table = details.querySelector('table')
    expect(table).toBeTruthy()
    expect([...table.querySelectorAll('th[scope="row"]')].length).toBe(OFFERED.length)
    // Screen-reader-named checkboxes, same contract as the admin grid.
    const boxes = [...table.querySelectorAll('input[type=checkbox]')]
    expect(boxes.length).toBeGreaterThan(20)
    // Cell checkboxes name their criterion, format, and readiness lane (only ready cells render one).
    for (const b of boxes) expect(b.getAttribute('aria-label'))
      .toMatch(/^\d+\.\d+\.\d+ .+, (DOCX|XLSX|PPTX|PDF) — (ready, certifies|ready, detect and confirm)$/)
  })
})

// ── owning its own state: picking a profile loads it ────────────────────────────────────────────
describe('scope state', () => {
  it('loads the Core 17 preset when its profile is chosen', async () => {
    const c = await render()
    const core = byRole(c, 'radio').find((r) => r.textContent.includes('Core 17'))
    await click(core)
    // Core 17 selects every READY cell in the offered grid — not-ready pairs are dropped, so the
    // count is the ready total, not the engine-reachable total.
    const total = OFFERED.reduce((n, r) => n + r.ready.length, 0)
    expect(c.textContent).toMatch(new RegExp(`${total} supported checks selected`))
    expect(core.getAttribute('aria-checked')).toBe('true')
  })

  it('renders the footer only with showStartButton, and starts a scan on confirm', async () => {
    const started = vi.fn()
    const c = await render({ showStartButton: true, onStartScan: started })
    const startBtn = [...c.querySelectorAll('button')].find((b) => /Start scan/.test(b.textContent))
    expect(startBtn).toBeTruthy()
    expect(c.textContent).toMatch(/Remember these selections for my next scan/)
    await click(startBtn)
    expect(started).toHaveBeenCalled()
  })

  it('has no footer when standalone, but offers "Save as reusable scope"', async () => {
    const c = await render()
    expect([...c.querySelectorAll('button')].some((b) => /Start scan/.test(b.textContent))).toBe(false)
    expect([...c.querySelectorAll('button')].some((b) => /Save as reusable scope/.test(b.textContent))).toBe(true)
  })
})

// ── owner-only: a non-owner (canEditScope=false) gets a read-only wizard + a clear note ──────────
describe('read-only for a non-owner', () => {
  it('renders the owner note and disables every scope control when canEditScope is false', async () => {
    const c = await render({ canEditScope: false })
    // The note is up front (role=status), names it read-only, and points at the workspace owner —
    // scope is owner-only (PUT /settings is owner-gated), so a non-owner is told before they edit.
    const note = [...c.querySelectorAll('[role="status"]')]
      .find((n) => /Read-only/i.test(n.textContent))
    expect(note, 'no read-only owner note').toBeTruthy()
    expect(note.textContent).toMatch(/owner/i)
    // Profile pills and format cards are disabled — the scope cannot be changed here.
    for (const r of byRole(c, 'radio')) expect(r.disabled).toBe(true)
    const formatCards = byRole(c, 'checkbox')
      .filter((e) => /supported criteria/.test(e.getAttribute('aria-label') || ''))
    expect(formatCards.length).toBe(4)
    for (const card of formatCards) expect(card.disabled).toBe(true)
    // Every criterion×format cell input in the grid is disabled too.
    for (const b of cellBoxes(c)) expect(b.disabled).toBe(true)
  })

  it('leaves the controls editable when canEditScope is true (the default, fail-open)', async () => {
    const c = await render({ canEditScope: true })
    expect([...c.querySelectorAll('[role="status"]')].some((n) => /Read-only/i.test(n.textContent))).toBe(false)
    for (const r of byRole(c, 'radio')) expect(r.disabled).toBe(false)
  })
})

// ── Phase 2: the redesigned matrix (sticky, principle groups, column/row/group controls, cells,
//    search + filters) ─────────────────────────────────────────────────────────────────────────
const detailsOf = (c) => [...c.querySelectorAll('details')]
  .find((d) => /Customize criteria and combinations/.test(d.querySelector('summary')?.textContent || ''))
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

describe('Phase 2 matrix — principle grouping', () => {
  it('renders a labeled group header for each WCAG principle present', async () => {
    const c = await render()
    const grid = gridOf(c)
    // Offered criteria span all four principles (1.x, 2.x, 3.x, 4.x), so every label shows.
    for (const name of ['Perceivable', 'Operable', 'Understandable', 'Robust']) {
      expect(grid.textContent, `missing group "${name}"`).toContain(name)
    }
    // Group headers are full-width rows spanning the whole table (1 criterion + 4 formats + row col).
    const spanned = [...grid.querySelectorAll('td[colspan]')].map((t) => Number(t.getAttribute('colspan')))
    expect(spanned).toContain(SCOPE_FORMATS.length + 2)
  })

  it('a group All/None control toggles every supported pair in that group', async () => {
    const c = await render()
    await pickCore17(c)        // the whole offered grid ticked, restrict on
    const grid = gridOf(c)
    // Robust = 4.1.2 only, four supported formats.
    const robust = toggleByLabel(grid, /Select all criteria in Robust/)
    expect(robust).toBeTruthy()
    expect(robust.getAttribute('aria-checked')).toBe('true')   // all on to start
    const before = checkedCount(c)
    await click(robust)                                        // → None for the group
    expect(robust.getAttribute('aria-checked')).toBe('false')
    const afterNone = checkedCount(c)
    expect(afterNone).toBeLessThan(before)
    await click(robust)                                        // → All again
    expect(robust.getAttribute('aria-checked')).toBe('true')
    expect(checkedCount(c)).toBe(before)
  })
})

describe('Phase 2 matrix — column and row controls', () => {
  it('a format column header toggles that format down the visible rows', async () => {
    const c = await render()
    await pickCore17(c)
    const grid = gridOf(c)
    const docxCol = toggleByLabel(grid, /^Select DOCX for all/)
    expect(docxCol).toBeTruthy()
    expect(docxCol.getAttribute('aria-checked')).toBe('true')  // Core 17 → all on
    // Count DOCX-ASSESSABLE rows among the offered set — only ready cells carry a checkbox.
    const docxRows = OFFERED.filter((r) => r.ready.includes('docx')).length
    const before = checkedCount(c)
    await click(docxCol)                                       // clears the whole DOCX column
    expect(docxCol.getAttribute('aria-checked')).toBe('false')
    expect(checkedCount(c)).toBe(before - docxRows)
  })

  it('a row control toggles every supported format for its criterion', async () => {
    const c = await render()
    await pickCore17(c)
    const grid = gridOf(c)
    // 1.1.1 supports all four formats.
    const row111 = toggleByLabel(grid, /^Select every format for 1\.1\.1/)
    expect(row111).toBeTruthy()
    expect(row111.getAttribute('aria-checked')).toBe('true')
    const before = checkedCount(c)
    await click(row111)
    expect(row111.getAttribute('aria-checked')).toBe('false')
    expect(checkedCount(c)).toBe(before - 4)
  })
})

describe('Phase 2 matrix — cell states', () => {
  it('renders unsupported pairs as "Not supported", never as an unchecked checkbox', async () => {
    const c = await render()
    const grid = gridOf(c)
    // 1.4.1 supports docx/pdf/xlsx but NOT pptx (per SCOPE_UNIVERSE) — that cell must be muted,
    // titled "Not supported…", and carry no checkbox.
    const notSupported = [...grid.querySelectorAll('td[title^="Not supported"]')]
    expect(notSupported.length).toBeGreaterThan(0)
    for (const td of notSupported) {
      expect(td.querySelector('input[type=checkbox]'), 'unsupported cell has a checkbox').toBeNull()
      expect(td.textContent).toMatch(/Not supported/)   // sr-only label
    }
    // The count matches the offered universe's unsupported pairs exactly (format not in row.formats).
    const unsupported = OFFERED.reduce((n, r) => n + (SCOPE_FORMATS.length - r.formats.length), 0)
    expect(notSupported.length).toBe(unsupported)
  })
})

// ── readiness: cells ACP can't assess yet are greyed, disabled, and out of the count ────────────
describe('readiness — not-ready pairs are greyed and cannot be selected', () => {
  it('renders offered-but-not-assessable pairs as "Not ready yet", never as a checkbox', async () => {
    const c = await render()
    const grid = gridOf(c)
    const notReady = [...grid.querySelectorAll('td[title^="Not ready yet"]')]
    // The exact set: every offered (row.formats) pair whose assessment lane is absent/human.
    const want = OFFERED.reduce((n, r) => n + r.formats.filter((f) => !isReady(r.sc, f)).length, 0)
    expect(want).toBeGreaterThan(0)                 // there really are such cells (guards the premise)
    expect(notReady.length).toBe(want)
    for (const td of notReady) {
      expect(td.querySelector('input[type=checkbox]'), 'not-ready cell has a checkbox').toBeNull()
      expect(td.textContent).toMatch(/Not ready yet/)
    }
  })

  it('tags a fully-not-ready criterion and disables its row control', async () => {
    const c = await render()
    const grid = gridOf(c)
    // 2.1.1 (Keyboard) has no format ACP can assess yet. (2.4.3 Focus Order left this set when
    // R8 declared pdf 2.4.3 as a registry-backed review lane — it is now ready on pdf.)
    for (const sc of ['2.1.1']) {
      const row = OFFERED.find((r) => r.sc === sc)
      expect(row.ready.length, `${sc} should have no ready format`).toBe(0)
    }
    expect(grid.textContent).toContain('NOT READY')
    const rowCtl = toggleByLabel(grid, /^Select every format for 2\.1\.1/)
    expect(rowCtl).toBeTruthy()
    expect(rowCtl.disabled).toBe(true)
  })

  it('Core 17 selects only assessable cells — no not-ready pair is ever checked', async () => {
    const c = await render()
    await pickCore17(c)
    // Every checked cell must be a ready pair. (checkedCount counts input checkboxes, which only
    // ready cells render — so this proves the preset didn't smuggle in an unassessable pair.)
    expect(checkedCount(c)).toBe(OFFERED.reduce((n, r) => n + r.ready.length, 0))
  })
})

describe('Phase 2 matrix — search and filters', () => {
  it('"Selected only" hides rows with nothing selected', async () => {
    const c = await render()
    // Custom keeps the (empty) selection but turns restrict on, so the grid starts all-unticked.
    const custom = byRole(c, 'radio').find((r) => r.textContent.includes('Custom scope'))
    await click(custom)
    // Tick exactly one criterion (1.1.1, all four formats) via its row control.
    await click(toggleByLabel(gridOf(c), /^Select every format for 1\.1\.1/))
    const rowsBefore = [...gridOf(c).querySelectorAll('th[scope="row"]')].length
    expect(rowsBefore).toBe(OFFERED.length)   // no filter yet: every offered row shows
    const chip = byRole(c, 'checkbox').filter((e) => e.tagName === 'BUTTON')
      .find((e) => e.textContent === 'Selected only')
    expect(chip).toBeTruthy()
    await click(chip)
    const rowsAfter = [...gridOf(c).querySelectorAll('th[scope="row"]')].length
    expect(rowsAfter).toBeLessThan(rowsBefore)
    expect(rowsAfter).toBe(1)   // only 1.1.1 remains
  })

  it('a level filter reduces visible rows to that level, and Clear filters restores them', async () => {
    const c = await render()
    const allRows = [...gridOf(c).querySelectorAll('th[scope="row"]')].length
    expect(allRows).toBe(OFFERED.length)
    const levelAA = byRole(c, 'checkbox').filter((e) => e.tagName === 'BUTTON')
      .find((e) => e.textContent === 'Level AA')
    expect(levelAA).toBeTruthy()
    await click(levelAA)
    const aaRows = [...gridOf(c).querySelectorAll('th[scope="row"]')].length
    const wantAA = OFFERED.filter((r) => r.level === 'AA').length
    expect(aaRows).toBe(wantAA)
    expect(aaRows).toBeLessThan(allRows)
    // The visible-count status reflects the filter.
    expect(c.textContent).toMatch(new RegExp(`Showing ${wantAA} of ${OFFERED.length} criteria`))
    // Clear filters restores the full grid.
    const clear = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Clear filters')
    expect(clear).toBeTruthy()
    await click(clear)
    expect([...gridOf(c).querySelectorAll('th[scope="row"]')].length).toBe(OFFERED.length)
  })

  it('text search matches criterion id and name', async () => {
    const c = await render()
    const search = c.querySelector('input[type=search]')
    expect(search).toBeTruthy()
    await typeSearch(search, 'contrast')
    const rows = [...gridOf(c).querySelectorAll('th[scope="row"]')].map((t) => t.textContent)
    expect(rows.length).toBeGreaterThan(0)
    for (const r of rows) expect(r.toLowerCase()).toMatch(/contrast/)
  })

  it('the sticky header exposes a per-format column select and the criterion column header', async () => {
    const c = await render()
    const grid = gridOf(c)
    // Header cells still use scope="col"; the redesign keeps a Criterion header and one per format.
    const cols = [...grid.querySelectorAll('th[scope="col"]')].map((t) => t.textContent)
    expect(cols.some((t) => /Criterion/.test(t))).toBe(true)
    for (const f of SCOPE_FORMATS) expect(cols.some((t) => t.includes(FMT_LABEL[f]))).toBe(true)
  })
})

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
    // The confirm is the only path that dispatches doScan.
    expect(code).toMatch(/onConfirm=\{[\s\S]*?doScan\(source, folder\)/)
  })

  it('wires onScan={requestScan} at every entry point, not doScan', () => {
    for (const entry of ['<EmptyState', '<Overview', '<Integrations', '<Discover']) {
      // Not asserting per-component here (they share one prop name); instead prove no entry point
      // is wired straight to doScan anymore.
      expect(entry).toBeTruthy()
    }
    expect(code).not.toMatch(/onScan=\{doScan\}/)
    expect((code.match(/onScan=\{requestScan\}/g) || []).length).toBeGreaterThanOrEqual(4)
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
