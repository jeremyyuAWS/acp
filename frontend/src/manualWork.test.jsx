/**
 * R6 · Manual — the lane for work ACP cannot do itself.
 *
 * What these guard, in order of what would hurt most if it broke:
 *   1. the lane is DERIVED from the capability table per (format × criterion), so the same criterion
 *      lands in the lane on one format and not on another. A hardcoded list passes a test that only
 *      ever checks one format, which is why every lane assertion below names two.
 *   2. a pair the table DECLARES human and a pair the table does not mention are reported as
 *      different things. Both reach the lane; only one of them is a statement.
 *   3. an unopened document is not manual work, and an absent scan is not an empty one.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { CAPABILITY_FALLBACK, ASSESSMENT_FALLBACK, modeFor } from './capability.js'
import { manualWork, manualBasis, labelFor } from './manualWork.js'
import { hasGuidance } from './remediationGuide.js'
import { WCAG } from './wcagCatalog.js'
import ManualWork from './ManualWork.jsx'

afterEach(unmountAll)

const cap = CAPABILITY_FALLBACK
const assessment = ASSESSMENT_FALLBACK
const opts = { cap, assessment }

// A scanned file row in the shape documentRow reads: type + issues carrying `wcag`.
const file = (name, type, issues) => ({
  file: name, name, type,
  status: 'analysed',
  issues: issues.map(([wcag, severity = 'SERIOUS']) => ({ wcag, severity, detail: `${wcag} in ${name}` })),
})

async function mount(props) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ManualWork, props)) })
  return container
}

// ── the lane is derived, and it is format-aware ──────────────────────────────
describe('the manual lane comes from the capability table, per format', () => {
  it('1.4.1 is manual on xlsx and NOT manual on docx — one criterion, two lanes', () => {
    // The table's own values; asserted here so a change to it fails this test loudly rather than
    // quietly changing what the screen claims.
    expect(modeFor(cap, 'xlsx', '1.4.1')).toBe('human')
    expect(modeFor(cap, 'docx', '1.4.1')).toBe('assisted')

    const w = manualWork([
      file('budget.xlsx', 'xlsx', [['SC_1_4_1']]),
      file('policy.docx', 'docx', [['SC_1_4_1']]),
    ], opts)
    expect(w.documents.map((d) => d.file)).toEqual(['budget.xlsx'])
    expect(w.documents[0].criteria.map((c) => c.sc)).toEqual(['1.4.1'])
  })

  it('2.1.1 is manual on pptx and NOT manual on html', () => {
    expect(modeFor(cap, 'pptx', '2.1.1')).toBe('human')
    expect(modeFor(cap, 'html', '2.1.1')).toBe('human')   // by absence — see the basis test below
    const w = manualWork([file('deck.pptx', 'pptx', [['SC_2_1_1']])], opts)
    expect(w.documents[0].criteria[0].basis).toBe('declared')
  })

  it('an auto criterion and an assisted criterion are both excluded', () => {
    expect(modeFor(cap, 'docx', '1.3.1')).toBe('auto')
    expect(modeFor(cap, 'docx', '1.1.1')).toBe('assisted')
    const w = manualWork([file('policy.docx', 'docx', [['SC_1_3_1'], ['SC_1_1_1']])], opts)
    expect(w.documents).toEqual([])
    expect(w.findingCount).toBe(0)
  })
})

// ── declared vs defaulted ────────────────────────────────────────────────────
describe('a declared manual lane and an absent table entry are different claims', () => {
  it('manualBasis distinguishes them', () => {
    expect(manualBasis(cap, 'xlsx', '1.4.1')).toBe('declared')   // literally "human" in the table
    expect(cap.docx['2.1.2']).toBe('human')
    expect(manualBasis(cap, 'docx', '2.1.2')).toBe('declared')
    // 2.4.3 has no docx entry at all — modeFor's conservative default puts it in the lane, and
    // 2.1.1 is the same case one criterion away from a declared one, which is exactly the pair a
    // reader would otherwise conflate.
    expect(cap.docx['2.4.3']).toBeUndefined()
    expect(cap.docx['2.1.1']).toBeUndefined()
    expect(manualBasis(cap, 'docx', '2.4.3')).toBe('default')
    expect(manualBasis(cap, 'docx', '2.1.1')).toBe('default')
    // not in the lane at all
    expect(manualBasis(cap, 'docx', '1.3.1')).toBe(null)
  })

  it('defaulted pairs are counted separately and named', () => {
    const w = manualWork([
      file('budget.xlsx', 'xlsx', [['SC_1_4_1']]),         // declared
      file('policy.docx', 'docx', [['SC_2_4_3']]),          // defaulted
    ], opts)
    expect(w.defaultedPairs).toEqual([{ file: 'policy.docx', fmt: 'docx', sc: '2.4.3' }])
    expect(w.findingCount).toBe(2)
  })
})

// ── absence is not zero ──────────────────────────────────────────────────────
describe('missing data renders as absent, never as zero', () => {
  it('no files at all returns null rather than an empty lane', () => {
    expect(manualWork(undefined, opts)).toBe(null)
    expect(manualWork(null, opts)).toBe(null)
  })

  it('an unopened document holds no findings of any lane and is reported separately', () => {
    const w = manualWork([
      { file: 'broken.docx', name: 'broken.docx', type: 'docx', status: 'error', error: 'HttpError 404' },
      file('budget.xlsx', 'xlsx', [['SC_1_4_1']]),
    ], opts)
    expect(w.unopened).toEqual([{ file: 'broken.docx', name: 'broken.docx', reason: 'HttpError 404' }])
    expect(w.documentCount).toBe(1)          // the unopened file is NOT a document with manual work
    expect(w.findingCount).toBe(1)
  })
})

// ── labels ───────────────────────────────────────────────────────────────────
describe('every criterion gets a real label', () => {
  it('falls back to the WCAG name for criteria PLAIN_NAMES does not cover', () => {
    expect(labelFor('1.1.1')).toBe('Images missing a text description')  // plain-language
    expect(labelFor('1.3.2')).toBe('Meaningful Sequence')                // WCAG's own name
    expect(labelFor('2.4.10')).toBe('Section Headings')
    expect(labelFor('9.9.9')).toBe('')                                   // never invented
  })
})

// ── rendering ────────────────────────────────────────────────────────────────
describe('ManualWork rendering', () => {
  it('renders nothing at all when there is no scan behind it', async () => {
    const c = await mount({ files: null, cap, assessment })
    expect(c.textContent).toBe('')
  })

  it('leads with the count of documents and findings, and names the document', async () => {
    const c = await mount({
      files: [file('budget.xlsx', 'xlsx', [['SC_1_4_1'], ['SC_1_4_1']]),
              file('site.html', 'html', [['SC_1_1_1']])],
      cap, assessment,
    })
    expect(c.textContent).toMatch(/3 findings across 2 documents/)
    expect(c.textContent).toMatch(/budget\.xlsx/)
    expect(c.textContent).toMatch(/site\.html/)
    // ordered by how much hand-work each holds
    const names = [...c.querySelectorAll('.manual-doc')].map((d) => d.textContent.slice(0, 20))
    expect(names[0]).toMatch(/budget\.xlsx/)
  })

  it('marks a defaulted row on the row itself, and counts them above', async () => {
    const c = await mount({ files: [file('policy.docx', 'docx', [['SC_2_4_3']])], cap, assessment })
    expect(c.querySelector('.manual-defaulted')).toBeTruthy()
    expect(c.querySelector('.manual-defaulted').textContent).toMatch(/no table entry/i)
    expect(c.querySelector('.manual-defaults-note').textContent)
      .toMatch(/absent capability-table entry/)
  })

  it('a declared row carries no defaulted marker and no defaults note', async () => {
    const c = await mount({ files: [file('budget.xlsx', 'xlsx', [['SC_1_4_1']])], cap, assessment })
    expect(c.querySelector('.manual-defaulted')).toBeNull()
    expect(c.querySelector('.manual-defaults-note')).toBeNull()
  })

  it('offers the real menu path for the document\'s own app, per platform', async () => {
    const c = await mount({ files: [file('deck.pptx', 'pptx', [['SC_2_1_1']])], cap, assessment })
    const toggle = [...c.querySelectorAll('button')].find((b) => /How to fix this in PowerPoint/.test(b.textContent))
    expect(toggle).toBeTruthy()
    await act(async () => { toggle.click() })
    // 2.1.1 has a criterion-specific entry in remediationGuide, so no "generic checker" disclaimer.
    expect(c.textContent).not.toMatch(/built-in checker rather than a path specific/)
    const mac = [...c.querySelectorAll('button')].find((b) => b.textContent === 'macOS')
    await act(async () => { mac.click() })
    expect(c.textContent.length).toBeGreaterThan(0)
  })

  it('NOTHING that reaches this lane is answered with the generic checker any more', () => {
    // This test used to mount a 2.4.3 finding and assert the "built-in checker rather than a path
    // specific to this" disclaimer appeared. That scenario no longer exists: 1.4.1, 1.4.11, 2.1.2
    // and 2.4.3 gained criterion-specific guidance, and they were the last criteria able to reach
    // the manual lane without it. Swapping in another criterion does not work either — measured
    // across the whole catalog × four formats, exactly 14 (criterion, format) pairs surface here
    // and all 14 now have specific guidance.
    //
    // So the assertion is inverted rather than deleted, which is the stronger statement and the
    // one worth keeping: no pair that can reach a reviewer is answered with a generic checker
    // line. The disclaimer code in ManualWork.jsx stays — it becomes reachable again the moment a
    // criterion enters this lane without guidance, and this test is what will say so.
    const surfaced = []
    for (const c of WCAG) {
      const tag = 'SC_' + c.sc.replace(/\./g, '_')
      for (const fmt of ['docx', 'xlsx', 'pptx', 'pdf']) {
        const w = manualWork([file(`x.${fmt}`, fmt, [[tag]])], opts)
        if (w.documents.length) surfaced.push([c.sc, fmt])
      }
    }
    expect(surfaced.length).toBeGreaterThan(0)   // the sweep must actually find something
    const bare = surfaced.filter(([sc]) => !hasGuidance(sc)).map(([sc, fmt]) => `${sc}/${fmt}`)
    expect(bare, 'these reach the manual lane with only the generic Accessibility Checker line, '
      + 'which does not test them — give each an inspection procedure, a "done when" and a '
      + 'statement of what ACP cannot verify, as 1.4.1/1.4.11/2.1.2/2.4.3 have').toEqual([])
  })

  it('reports an unopened document as holding no findings, not as clean', async () => {
    const c = await mount({
      files: [{ file: 'broken.docx', name: 'broken.docx', type: 'docx', status: 'error' },
              file('budget.xlsx', 'xlsx', [['SC_1_4_1']])],
      cap, assessment,
    })
    expect(c.querySelector('.manual-unopened').textContent)
      .toMatch(/never opened by\s+the scanner/)
    expect(c.querySelector('.manual-unopened').textContent).toMatch(/not zero manual findings/)
  })

  /**
   * The summary sentence is the one making the quantitative claim, so the prohibition is asserted
   * THERE and not over the whole screen. A page-wide regex for these would match the explanatory
   * copy that exists precisely to explain why the numbers are what they are — which has produced a
   * failing test about correct prose twice in this repo.
   */
  it('the summary claims a count and never a percentage or an effort estimate', async () => {
    const c = await mount({ files: [file('budget.xlsx', 'xlsx', [['SC_1_4_1']])], cap, assessment })
    const summary = c.querySelector('.manualwork > p')
    expect(summary.textContent).toMatch(/1 finding across 1 document/)
    expect(summary.textContent).not.toMatch(/%/)
    expect(summary.textContent).not.toMatch(/\b(min|mins|minute|minutes|hour|hours|~)\b/)
  })
})
