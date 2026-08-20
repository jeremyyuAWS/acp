/**
 * The Assess PRE-RUN screen (board 2 of the redesign), RENDERED, plus the source assertions the
 * DOM cannot make.
 *
 * TWO LANES, and they are not interchangeable.
 *
 * The DOM lane pins what a reader sees: the exclusion arithmetic adds up on screen, the
 * acknowledgement states the fraction in words and gates the run, the conformance target is
 * derived from the criteria, a missing count renders nothing rather than 0, and an empty scope
 * states its cause instead of offering a run that would assess nothing.
 *
 * The SOURCE lane pins the ABSENCES — the things this board exists to remove. A screen with no
 * level selector, no time estimate and no score looks exactly like a screen where someone forgot
 * to add them; nothing in the rendered output distinguishes "deliberately absent" from "not
 * written yet", and a future edit that adds a Level A/AA/AAA dropdown would break no DOM
 * assertion at all. So those are asserted against the module text.
 *
 * DOM-level, not browser-level: the preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (CLAUDE.md), so this renders the component directly against mocked
 * API calls and never through the browser pane.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const api = { getSettings: null, updateSettings: null, fetchCodeset: null, fetchEligibility: null }
vi.mock('./api.js', () => ({
  getSettings: (...a) => api.getSettings(...a),
  updateSettings: (...a) => api.updateSettings(...a),
  fetchCodeset: (...a) => api.fetchCodeset(...a),
  fetchEligibility: (...a) => api.fetchEligibility(...a),
}))

const { default: AssessSetup, deriveLevel } = await import('./AssessSetup.jsx')
const { SCOPE_UNIVERSE } = await import('./scopePresets.js')
const { TRACKED_17 } = await import('./ruleDetails.js')

// The catalogue the endpoint would return — derived from the same generated tables the UI reads,
// never a second hand-typed list.
const CODESET = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))
  .map((r) => ({ code: r.sc, name: r.name, formats: [...r.formats] }))

// The board's own worked example, as an eligibility response: 12,408 discovered, 12,340 with no
// assessment lane at all, 40 eligible across the four document formats, 18 of those tagged for
// archive/deletion review — leaving 22 to assess.
const BOARD = {
  discovered: 12408,
  eligible: 40,
  by_format: { docx: 16, pdf: 12, pptx: 8, xlsx: 4 },
  formats: ['docx', 'pdf', 'pptx', 'xlsx'],
  codes: [],
  lifecycle_excluded: 31,
  lifecycle_eligible_excluded: 18,
}

async function render(props = {}, { elig = BOARD, scan_scope = '' } = {}) {
  api.getSettings = vi.fn(async () => ({ scan_scope }))
  api.updateSettings = vi.fn(async () => ({}))       // not simulated → a real save
  api.fetchCodeset = vi.fn(async () => CODESET)
  api.fetchEligibility = vi.fn(async () => elig)
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(AssessSetup, { onRun: vi.fn(), ...props })) })
  await settle()
  return { c: container }
}

// The eligibility fetch is debounced (300ms); a real wait lets it fire and its state settle.
const settle = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 360)) }) }
const click = async (el) => { await act(async () => { el.click() }) }
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
const text = (c, sel) => c.querySelector(sel)?.textContent || ''
// Digits only, so an assertion about arithmetic is not also an assertion about thin spaces or
// whichever grouping separator the test runner's locale happens to use.
const nums = (s) => (s.match(/[\d,]*\d/g) || []).map((x) => Number(x.replace(/[^\d]/g, '')))
const ackBox = (c) => c.querySelector('.assesssetup-ack input[type=checkbox]')
const runBtn = (c) => c.querySelector('button.assesssetup-run')

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = readFileSync(join(HERE, 'AssessSetup.jsx'), 'utf8')
// Only the code — the module's comments discuss the score, the estimates and the removed selector
// at length, and a naive grep over the whole file would fail on the prose explaining the absence.
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')


describe('the exclusion arithmetic adds up on screen', () => {
  it('names every excluded population and prints the parts summing to the discovered total', async () => {
    const { c } = await render()
    const box = text(c, '.assesssetup-exclusions')
    // 12,408 discovered − 40 eligible = 12,368 with no assessment method; 40 − 40 in the selected
    // types = 0 deselected (so no row); 18 tagged. 12,368 + 18 = 12,386 excluded, 22 assessed.
    expect(box).toContain('12,368')
    expect(box).toContain('18')
    expect(box).toContain('tagged for archive or deletion review by a lifecycle rule')

    const line = text(c, '.assesssetup-reconcile')
    const parts = nums(line)
    expect(line).toMatch(/= 12,408 discovered$/)
    // The identity itself, not just its presence: the printed parts sum to the printed whole.
    const whole = parts.pop()
    expect(parts.reduce((a, b) => a + b, 0)).toBe(whole)
    expect(whole).toBe(12408)
    expect(parts).toEqual([12368, 18, 22])
  })

  it('renders no row for a population that is empty — a zero is not an exclusion', async () => {
    // Every discovered file is eligible and none is tagged: only the document-type deselection
    // can produce a row, and here nothing is deselected either.
    const { c } = await render({}, { elig: { discovered: 40, eligible: 40,
      by_format: { docx: 40 }, formats: ['docx'], codes: [] } })
    expect(c.querySelector('.assesssetup-exclusions')).toBeNull()
    expect(c.textContent).toContain('Nothing is excluded')
    expect(c.textContent).not.toMatch(/\b0\s+(?:excluded|tagged)/)
  })
})


describe('the acknowledgement states the fraction, and the run waits for it', () => {
  it('spells out "Assessing 22 of 12,408 discovered files" and blocks the run until it is ticked', async () => {
    const onRun = vi.fn()
    const { c } = await render({ onRun })
    expect(text(c, '.assesssetup-ack')).toContain('Assessing 22 of 12,408 discovered files')

    // THE ASSERTION THIS FILE EXISTS FOR. A run that quietly assesses 22 of 12,408 without the
    // operator seeing that ratio is the failure this screen prevents, so the gate is the feature.
    expect(runBtn(c).disabled).toBe(true)
    await click(runBtn(c))
    expect(onRun).not.toHaveBeenCalled()

    await click(ackBox(c))
    expect(runBtn(c).disabled).toBe(false)
    await click(runBtn(c))
    expect(onRun).toHaveBeenCalledTimes(1)
    expect(onRun.mock.calls[0][0]).toMatchObject({ documents: 22, discovered: 12408, excluded: 12386 })
  })

  it('un-ticks itself when the selection changes, so it never acknowledges unseen numbers', async () => {
    const { c } = await render()
    await click(ackBox(c))
    expect(runBtn(c).disabled).toBe(false)

    await click(btn(c, /change document types/))
    await click([...c.querySelectorAll('button[aria-pressed]')].find((b) => /PDF/i.test(b.textContent)))
    await settle()
    expect(ackBox(c).checked).toBe(false)
    expect(runBtn(c).disabled).toBe(true)
  })

  it('does not demand an acknowledgement when nothing is excluded', async () => {
    const { c } = await render({}, { elig: { discovered: 40, eligible: 40,
      by_format: { docx: 40 }, formats: ['docx'], codes: [] } })
    expect(ackBox(c)).toBeNull()
    expect(runBtn(c).disabled).toBe(false)
  })
})


describe('the conformance target is derived, never selected', () => {
  it('states it as derived from the criteria', async () => {
    const { c } = await render()
    const t = text(c, '.assesssetup-target')
    expect(t).toMatch(/Conformance target: WCAG 2\.1 Level AA/)
    expect(t).toContain('derived from the criteria above, not chosen separately')
  })

  it('takes the highest level present in the selection', () => {
    // The whole rule, stated directly rather than inferred from rendered text.
    expect(deriveLevel(['1.1.1', '1.3.1'])).toBe('A')          // all Level A
    expect(deriveLevel(['1.1.1', '1.4.3'])).toBe('AA')         // one AA lifts it
    expect(deriveLevel(['1.1.1', '1.4.6'])).toBe('AAA')        // one AAA lifts it further
    expect(deriveLevel([])).toBe(null)                          // nothing to derive from
  })

  it('offers no control that could disagree with the criteria', async () => {
    const { c } = await render()
    expect(c.querySelector('select')).toBeNull()
    const labels = [...c.querySelectorAll('button')].map((b) => b.textContent.trim())
    expect(labels).not.toContain('AAA')
    expect(labels).not.toContain('AA')
    expect(labels).not.toContain('A')
  })
})


describe('a missing count renders nothing, never 0', () => {
  it('shows no document count at all while the eligibility fetch has produced nothing', async () => {
    api.getSettings = vi.fn(async () => ({ scan_scope: '' }))
    api.updateSettings = vi.fn(async () => ({}))
    api.fetchCodeset = vi.fn(async () => CODESET)
    api.fetchEligibility = vi.fn(async () => { throw new Error('no discovery run') })
    const { root, container: c } = createTestRoot()
    await act(async () => { root.render(createElement(AssessSetup, { onRun: vi.fn() })) })
    await settle()

    expect(text(c, '.assesssetup-documents')).not.toMatch(/\b0\b/)
    expect(c.textContent).not.toContain('0 documents')
    expect(c.textContent).not.toContain('files listed')
    expect(c.querySelector('.assesssetup-exclusions')).toBeNull()
    expect(c.querySelector('.assesssetup-onenumber')).toBeNull()
    expect(runBtn(c).disabled).toBe(true)
  })
})


describe('nothing to assess states the cause, and never renders a run', () => {
  it('names the narrowing and offers the control that fixes it', async () => {
    const { c } = await render({}, { elig: { discovered: 12408, eligible: 40,
      by_format: { pdf: 40 }, formats: ['pdf'], codes: [] } })
    // Untick PDF: every eligible file is now in a document type the operator excluded.
    await click(btn(c, /change document types/))
    await click([...c.querySelectorAll('button[aria-pressed]')].find((b) => /PDF/i.test(b.textContent)))
    await settle()

    const empty = text(c, '.assesssetup-empty')
    expect(empty).toContain('Nothing to assess')
    expect(empty).toContain('12,408')
    expect(empty).toContain('document-type selection')
    expect(runBtn(c)).toBeNull()                  // never a run that would assess nothing
    expect(btn(c, /Change document types/)).toBeTruthy()
  })

  it('says no discovery has run rather than reporting an empty estate', async () => {
    const { c } = await render({}, { elig: { discovered: 0, eligible: 0, by_format: {},
      formats: [], codes: [] } })
    expect(text(c, '.assesssetup-empty')).toContain('No discovery run has listed an estate yet')
    expect(c.querySelector('.assesssetup-exclusions')).toBeNull()
    expect(c.textContent).not.toContain('0 files listed')
  })
})


describe('the lifecycle tag is a recommendation, and can be overridden', () => {
  it('never says a file was archived or deleted', async () => {
    const { c } = await render()
    expect(c.textContent).toContain('tagged for archive or deletion review by a lifecycle rule')
    // A rule writes a recommendation on a discovered file; it moves nothing and deletes nothing.
    // Saying otherwise describes an action nobody took.
    expect(c.textContent).not.toMatch(/\b\d[\d,]*\s+archived\b/)
    expect(c.textContent).not.toMatch(/\b\d[\d,]*\s+deleted\b/)
    expect(c.textContent).not.toMatch(/(?:were|was|have been|has been)\s+(?:archived|deleted)/)
  })

  it('pulls the tagged files back into the run, and the arithmetic follows', async () => {
    const onRun = vi.fn()
    const { c } = await render({ onRun })
    expect(text(c, '.assesssetup-ack')).toContain('Assessing 22 of 12,408')

    await click(btn(c, /include them/))
    await settle()
    // 18 tagged files return: 22 + 18 = 40 assessed, and the exclusion row is gone.
    expect(text(c, '.assesssetup-ack')).toContain('Assessing 40 of 12,408')
    expect(text(c, '.assesssetup-exclusions')).not.toContain('tagged for archive or deletion review')
    const parts = nums(text(c, '.assesssetup-reconcile'))
    expect(parts).toEqual([12368, 40, 12408])

    await click(ackBox(c))
    await click(runBtn(c))
    expect(onRun.mock.calls[0][0]).toMatchObject({ includeLifecycleFlagged: true, documents: 40 })
  })
})


describe('one number defines the run', () => {
  it('prints documents × criteria = checks, with both factors beside it', async () => {
    const { c } = await render()
    const one = text(c, '.assesssetup-onenumber')
    const [docs, crit, checks] = nums(one)
    expect(docs).toBe(22)
    expect(crit).toBe(17)
    expect(checks).toBe(docs * crit)
    expect(runBtn(c).textContent).toContain('Assess 22 documents')
  })
})


describe('the run carries exactly what was decided here', () => {
  it('writes scan_scope as the selection, then hands the parent the descriptor', async () => {
    const onRun = vi.fn()
    const onSaved = vi.fn()
    const { c } = await render({ onRun, onSaved })
    await click(ackBox(c))
    await click(runBtn(c))

    expect(api.updateSettings).toHaveBeenCalledTimes(1)
    const scope = JSON.parse(api.updateSettings.mock.calls.at(-1)[0].scan_scope)
    expect(Object.keys(scope).sort()).toEqual(CODESET.map((r) => r.code).sort())
    expect(onSaved).toHaveBeenCalledWith(scope)
    expect(onRun.mock.calls[0][0]).toMatchObject({
      scope, criteria: 17, documents: 22, checks: 374, level: 'AA',
      includeLifecycleFlagged: false,
    })
  })
})


// ── SOURCE LANE — the absences, which no rendered output can distinguish from an oversight ─────
describe('what this board removed stays removed', () => {
  it('has no conformance-target selector in the source', () => {
    expect(CODE).not.toMatch(/setLevel|levelPicker|targetLevel\s*=/)
    // A segmented control or dropdown offering the three levels is the specific shape removed.
    expect(CODE).not.toMatch(/['"]AAA['"]\s*[,\]].*['"]AA['"]/)
    expect(CODE).not.toContain('<select')
    // …and the one place a level IS produced says out loud that it is derived.
    expect(CODE).toContain('export function deriveLevel')
    expect(CODE).toContain('derived from the criteria above, not chosen separately')
  })

  it('makes no estimate of time or effort', () => {
    // effort.js is the module that produces "est. 29.1 hrs" / "19 minutes per person". Importing
    // it is the only way this screen could grow one back without somebody typing the words.
    expect(SRC).not.toMatch(/from\s+['"]\.\/effort\.js['"]/)
    // Whole words: "metadata" and "details" both contain "eta", and a substring match here
    // would fail on prose that has nothing to do with an estimate.
    for (const word of ['minutes?', 'hours?', 'ETA', 'estimated?', 'roughly', 'approximately']) {
      expect(CODE, `"${word}" appears in the rendered code`)
        .not.toMatch(new RegExp(`\\b${word}\\b`, 'i'))
    }
  })

  it('computes no score and no bare percentage', () => {
    expect(CODE).not.toMatch(/\bscore\b/i)
    expect(CODE).not.toMatch(/\bcompliant\b/i)
    // `scopeImpact` returns a `pct`; this screen deliberately does not read it, because a
    // percentage on this board would be a ratio whose denominator the reader has to reconstruct.
    expect(CODE).not.toMatch(/impact\.pct|\.pct\b/)
    expect(CODE).not.toContain('%')
  })

  it('takes its population arithmetic from the one unit-tested derivation', () => {
    // Not a second implementation of the funnel. Four answers to "how many files" on one screen is
    // the defect the whole redesign is about, and a private copy here would be the fifth.
    expect(SRC).toMatch(/import \{ scopeImpact, coverageGaps \} from '\.\/scopeImpact\.js'/)
    expect(CODE).not.toMatch(/discovered\s*-\s*eligible/)
  })

  it('reads assessMetrics not at all — this board reports on no run', () => {
    // Board 2 owns the decisions; board 4 owns the outcomes. A pre-run screen that imported the
    // results metrics would be one edit away from rendering a partially-filled count as a verdict.
    expect(SRC).not.toMatch(/from\s+['"]\.\/assessMetrics\.js['"]/)
  })
})
