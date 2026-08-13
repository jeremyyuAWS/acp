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

// Derived exactly as the component derives them — the universe narrowed to the tracked criteria,
// then a per-format count. This is the answer the cards must show.
const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))
const FMT_COUNT = Object.fromEntries(
  SCOPE_FORMATS.map((f) => [f, OFFERED.filter((r) => r.formats.includes(f)).length]),
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
    // Everything supported evaluates the whole offered grid.
    const total = OFFERED.reduce((n, r) => n + r.formats.length, 0)
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
    // Guard the numbers themselves so a regression in the derivation is visible here.
    expect(FMT_COUNT).toEqual({ docx: 15, xlsx: 15, pptx: 16, pdf: 15 })
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
    for (const b of boxes) expect(b.getAttribute('aria-label')).toMatch(/^\d+\.\d+\.\d+ .+, (DOCX|XLSX|PPTX|PDF)$/)
  })
})

// ── owning its own state: picking a profile loads it ────────────────────────────────────────────
describe('scope state', () => {
  it('loads the Core 17 preset when its profile is chosen', async () => {
    const c = await render()
    const core = byRole(c, 'radio').find((r) => r.textContent.includes('Core 17'))
    await click(core)
    // Core 17 is the whole offered grid (17 criteria, every supported format).
    const total = OFFERED.reduce((n, r) => n + r.formats.length, 0)
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

// ── source-level: Integrations mounts the wizard and gates the scan behind the modal ────────────
const HERE = dirname(fileURLToPath(import.meta.url))
const codeOf = (f) => readFileSync(join(HERE, f), 'utf8')
  .split('\n')
  .filter((l) => {
    const t = l.trim()
    return !t.startsWith('//') && !t.startsWith('/*') && !t.startsWith('*') && !t.startsWith('{/*')
  })
  .join('\n')

describe('Integrations wires the wizard', () => {
  const code = codeOf('Integrations.jsx')

  it('imports and mounts the wizard', () => {
    expect(code).toMatch(/import ScanScopeWizard from '\.\/ScanScopeWizard\.jsx'/)
    expect(code).toMatch(/<ScanScopeWizard/)
  })

  it('routes "Scan all sources" through a required modal, not a direct scan', () => {
    // The button opens the modal instead of dispatching the scan inline.
    expect(code).toMatch(/setScanModalOpen\(true\)/)
    // The modal is a real dialog carrying the wizard with a Start button and a scan callback.
    expect(code).toMatch(/role="dialog"[\s\S]*aria-modal="true"/)
    expect(code).toMatch(/<ScanScopeWizard showStartButton/)
    expect(code).toMatch(/onStartScan=\{[^}]*runTheScan\(\)/)
  })
})
