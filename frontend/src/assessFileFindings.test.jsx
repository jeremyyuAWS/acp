/**
 * The per-file findings view — level 3 of the drill-down.
 *
 * Two lanes, because half of what this component must NOT do leaves no trace in the DOM:
 *
 *   · DOM/behaviour — what a reader sees: the numbers, the grouping, the two bands, the printed
 *     partition, the absence of drafts and of any apply/approve control.
 *   · SOURCE — what the module may not contain: a `.sort()` of its own (the ordering is the
 *     metrics module's and carries the product decision), any arithmetic that re-derives a metric,
 *     any import that could generate content, and any percentage/score/effort figure.
 *
 * A component that renders the right thing today and re-sorts tomorrow passes every DOM assertion
 * here, which is exactly why the source lane exists.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import { documentRow, findingsByCriterion } from './assessMetrics.js'
import AssessFileFindings from './AssessFileFindings.jsx'

afterEach(unmountAll)

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = readFileSync(join(HERE, 'AssessFileFindings.jsx'), 'utf8')

// A deliberately small, fully-stated world: five selected criteria, one format. Every number the
// component prints is checkable against these two tables by hand, which is the point — a fixture
// that needs the implementation to interpret it cannot catch the implementation being wrong.
const CRITERIA = new Set(['1.1.1', '1.3.1', '1.4.3', '2.4.2', '1.3.2'])
const CAP = {
  pdf: { '1.1.1': 'assisted', '1.3.1': 'auto', '1.4.3': 'auto', '2.4.2': 'auto' },
}
const ASMT = {
  // 1.3.2 is deliberately absent → no method for pdf → neither a pass nor a failure.
  pdf: { '1.1.1': 'review', '1.3.1': 'auto', '1.4.3': 'auto', '2.4.2': 'auto' },
}

const finding = (sc, severity, over = {}) =>
  ({ wcag: `SC_${sc.replace(/\./g, '_')}`, severity, ...over })

const doc = (issues, over = {}) =>
  ({ file: 'Finance/Q3 Board Pack.pdf', name: 'Finance/Q3 Board Pack.pdf', type: 'pdf',
     status: 'analysed', issues, ...over })

const rowFor = (f) => documentRow(f, { cap: CAP, assessment: ASMT, criteria: CRITERIA, level: 'AA' })

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(AssessFileFindings, {
      cap: CAP, assessment: ASMT, criteria: CRITERIA, ...props,
    }))
  })
  return container
}

// Element boundaries become spaces. `textContent` concatenates adjacent elements with nothing
// between them — "Serious1.1.1", "Findings4" — which makes every assertion below depend on the
// markup's nesting rather than on what a reader sees. Replacing tags with a space reads the page
// the way it is read aloud, so a wrapping <div> added later does not redden an unrelated test.
const text = (c) => c.innerHTML
  .replace(/<[^>]*>/g, ' ')
  .replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'").replace(/&amp;/g, '&')
  .replace(/\s+/g, ' ').trim()
const buttons = (c) => [...c.querySelectorAll('button')].map((b) => b.textContent.trim())

// The estate document used by most cases: 1.1.1 needs a person (assisted), 1.3.1 and 2.4.2 are
// deterministic, 1.4.3 is deterministic. So exactly one criterion needs a person.
const FILE = doc([
  finding('1.1.1', 'SERIOUS', { page: 2, detail: 'Chart image has no alt text' }),
  finding('1.1.1', 'SERIOUS', { page: 7, detail: 'Logo image has alt text “image1.png”' }),
  finding('1.3.1', 'CRITICAL', { page: 4, detail: 'Table “Revenue by region” has no header row' }),
  finding('2.4.2', 'MINOR', { detail: 'Document title is empty' }),
])

describe('AssessFileFindings — nothing, rather than zeros', () => {
  it('renders null for a missing row', async () => {
    const c = await mount({ row: null, file: null })
    expect(c.textContent).toBe('')
  })

  it('renders null for a document that could not be opened — not "0 findings"', async () => {
    const unopened = doc([], { status: 'error', error: 'password-protected' })
    const row = rowFor(unopened)
    expect(row.opened).toBe(false)

    const c = await mount({ row })
    expect(c.textContent).toBe('')
    // The claim under test, stated the way it would actually go wrong.
    expect(c.textContent).not.toMatch(/\b0\b/)
  })
})

describe('AssessFileFindings — every number comes from assessMetrics', () => {
  it('prints the row’s own findings, severity, auto-fix and review counts', async () => {
    const row = rowFor(FILE)
    const c = await mount({ row, file: FILE })
    const t = text(c)

    expect(row.totalFindings).toBe(4)
    expect(row.autoFixAvailable).toBe(2)      // 1.3.1 + 2.4.2
    expect(row.humanReviewRequired).toBe(2)   // two 1.1.1 findings, assisted
    expect(t).toMatch(/Findings 4/)
    expect(t).toMatch(/1 critical/)
    expect(t).toMatch(/2 serious/)
    expect(t).toMatch(/1 minor/)
    expect(t).toMatch(/Auto-fix available 2/)
    expect(t).toMatch(/Human review required 2/)
  })

  it('states coverage as a fraction of the selected criteria for this file', async () => {
    const row = rowFor(FILE)
    expect(row.criteriaEvaluated.length).toBe(4)
    expect(row.selectedChecks).toBe(5)

    const t = text(await mount({ row, file: FILE }))
    expect(t).toMatch(/4 of 5 criteria evaluated/)
    expect(t).toMatch(/1 has no method for PDF/)
  })
})

describe('AssessFileFindings — grouped by criterion, inside the file', () => {
  it('renders one group per failing criterion, with its name and level from the catalogue', async () => {
    const t = text(await mount({ row: rowFor(FILE), file: FILE }))
    expect(t).toMatch(/1\.1\.1 Non-text Content/)
    expect(t).toMatch(/1\.3\.1 Info and Relationships/)
    expect(t).toMatch(/2\.4\.2 Page Titled/)
    expect(t).toMatch(/Level A/)
    expect(t).toMatch(/3 criteria failing, 4 findings/)
  })

  it('lists every finding with where it is and what is wrong', async () => {
    const t = text(await mount({ row: rowFor(FILE), file: FILE }))
    expect(t).toMatch(/Page 2 Chart image has no alt text/)
    expect(t).toMatch(/Page 4 Table “Revenue by region” has no header row/)
    // A finding the analyser could not place gets no location rather than a wrong one.
    expect(t).toMatch(/Document title is empty/)
    expect(t).not.toMatch(/Page (undefined|NaN|0)/)
  })

  it('uses "Slide" for a deck and "Page" for a PDF', async () => {
    const deck = doc([finding('1.3.1', 'CRITICAL', { page: 3, detail: 'Table has no header row' })],
                     { file: 'Brand.pptx', name: 'Brand.pptx', type: 'pptx' })
    const cap = { pptx: { '1.3.1': 'auto' } }
    const asmt = { pptx: { '1.3.1': 'auto' } }
    const row = documentRow(deck, { cap, assessment: asmt, criteria: CRITERIA, level: 'AA' })
    const t = text(await mount({ row, file: deck, cap, assessment: asmt }))
    expect(t).toMatch(/Slide 3/)
    expect(t).not.toMatch(/Page 3/)
  })
})

describe('AssessFileFindings — auto means DETERMINISTIC, and all three modes read differently', () => {
  it('distinguishes auto, assisted and human in the finding rows', async () => {
    // One criterion per mode, so all three sentences must appear at once.
    const cap = { pdf: { '1.3.1': 'auto', '1.1.1': 'assisted', '1.4.3': 'human' } }
    const asmt = { pdf: { '1.3.1': 'auto', '1.1.1': 'review', '1.4.3': 'auto' } }
    const f = doc([
      finding('1.3.1', 'CRITICAL', { detail: 'Table has no header row' }),
      finding('1.1.1', 'SERIOUS', { detail: 'Chart image has no alt text' }),
      finding('1.4.3', 'SERIOUS', { detail: 'Caption text at 2.9:1' }),
    ])
    const row = documentRow(f, { cap, assessment: asmt, criteria: CRITERIA, level: 'AA' })
    const t = text(await mount({ row, file: f, cap, assessment: asmt }))

    expect(t).toMatch(/Fixed automatically in remediation/)
    expect(t).toMatch(/AI drafts it in remediation, you approve it there/)
    expect(t).toMatch(/You author it in remediation/)

    // The metric contract: an AI-drafted fix is NOT auto-fixable. One deterministic finding.
    expect(row.autoFixAvailable).toBe(1)
    expect(row.humanReviewRequired).toBe(2)
    expect(t).toMatch(/Auto-fix available 1/)
    expect(t).toMatch(/Human review required 2/)
  })

  it('a single-mode group says which mode, in the plural the count needs', async () => {
    const t = text(await mount({ row: rowFor(FILE), file: FILE }))
    expect(t).toMatch(/AI drafts 2 fixes in remediation, you approve them there/)
    expect(t).toMatch(/ACP fixes this one automatically in remediation/)
  })

  it('a group whose findings differ by mode lists each mode, never "some auto"', async () => {
    // TODAY THIS CANNOT ARISE FROM A REAL SCAN: `fixMode` is per (format, criterion), so every
    // finding grouped under one criterion carries the same mode. It is covered anyway because the
    // approved board's 1.4.3 group is exactly this shape ("1 fixed automatically, 1 needs a
    // person"), which is only expressible once a finding carries its own fixMode — and a sentence
    // that silently reported the first mode would hide the half that needs somebody.
    const row = rowFor(FILE)
    const i = row.findings.findIndex((x) => x.sc === '1.1.1')
    row.findings[i] = { ...row.findings[i], auto: true, fixMode: 'auto' }
    row.autoFixAvailable += 1
    row.humanReviewRequired -= 1

    const t = text(await mount({ row, file: FILE }))
    expect(t).toMatch(/1 fixed automatically, 1 AI-drafted for your approval — all in remediation/)
  })
})

describe('AssessFileFindings — ordered by what needs a person, and nothing is hidden', () => {
  // The ordering decision, pinned: a MINOR criterion needing somebody outranks a CRITICAL one ACP
  // fixes deterministically, because after remediation runs only the first still costs a person.
  const cap = { pdf: { '1.3.1': 'auto', '1.1.1': 'assisted' } }
  const asmt = { pdf: { '1.3.1': 'auto', '1.1.1': 'review' } }
  const MIXED = doc([
    finding('1.3.1', 'CRITICAL', { detail: 'Table has no header row' }),
    finding('1.1.1', 'MINOR', { detail: 'Decorative image has no alt text' }),
  ])

  it('renders the MINOR group needing a person above the auto-fixable CRITICAL one', async () => {
    const row = documentRow(MIXED, { cap, assessment: asmt, criteria: CRITERIA, level: 'AA' })
    const groups = findingsByCriterion(row)
    expect(groups.map((g) => g.sc)).toEqual(['1.1.1', '1.3.1'])
    expect(groups[0].needsPerson).toBe(true)

    const c = await mount({ row, file: MIXED, cap, assessment: asmt })
    const t = text(c)
    expect(t.indexOf('1.1.1')).toBeLessThan(t.indexOf('1.3.1'))
    // And the order is the module's: the DOM order equals the order it handed over.
    const rendered = [...t.matchAll(/\b(\d+\.\d+\.\d+) [A-Z]/g)].map((m) => m[1])
    expect(rendered.slice(0, 2)).toEqual(['1.1.1', '1.3.1'])
  })

  it('labels the two bands, so the ordering rule is visible rather than merely obeyed', async () => {
    const row = documentRow(MIXED, { cap, assessment: asmt, criteria: CRITERIA, level: 'AA' })
    const t = text(await mount({ row, file: MIXED, cap, assessment: asmt }))
    expect(t).toMatch(/Needs a person/)
    expect(t).toMatch(/ACP fixes these in remediation/)
  })

  it('DE-EMPHASIS IS NOT A FILTER — the deprioritised group keeps its severity and its findings', async () => {
    const row = documentRow(MIXED, { cap, assessment: asmt, criteria: CRITERIA, level: 'AA' })
    const t = text(await mount({ row, file: MIXED, cap, assessment: asmt }))
    // The auto-fixable group is last, and still says CRITICAL, still names its finding.
    expect(t).toMatch(/Critical/)
    expect(t).toMatch(/1\.3\.1 Info and Relationships/)
    expect(t).toMatch(/Table has no header row/)
    expect(t).toMatch(/1 critical/)   // and it is still counted in the file's severity mix
  })

  it('renders a single band when every group is on the same side', async () => {
    const allAuto = doc([finding('1.3.1', 'CRITICAL', { detail: 'Table has no header row' })])
    const row = documentRow(allAuto, { cap, assessment: asmt, criteria: CRITERIA, level: 'AA' })
    const t = text(await mount({ row, file: allAuto, cap, assessment: asmt }))
    expect(t).toMatch(/ACP fixes these in remediation/)
    expect(t).not.toMatch(/Needs a person/)
  })
})

describe('AssessFileFindings — nothing is drafted, approved or applied here', () => {
  it('renders no drafted content', async () => {
    const t = text(await mount({ row: rowFor(FILE), file: FILE }))
    expect(t).not.toMatch(/\bdraft(ed)?:/i)
    // A draft would arrive as a quoted replacement string; none of the finding rows carry one.
    expect(t).not.toMatch(/Draft unavailable/i)
    expect(t).not.toMatch(/Needs approval/i)
  })

  it('offers no control that applies or approves a fix', async () => {
    const c = await mount({ row: rowFor(FILE), file: FILE, onRemediate: () => {} })
    const labels = buttons(c)
    expect(labels).not.toContain('Approve')
    expect(labels).not.toContain('Apply')
    for (const l of labels) {
      expect(l).not.toMatch(/^(approve|apply|fix now|review \d+ drafts?)/i)
    }
    // The one action there is routes onward rather than acting here.
    expect(labels).toContain('Send to remediation')
  })

  it('says so on the page, because a reader cannot check an absence', async () => {
    const t = text(await mount({ row: rowFor(FILE), file: FILE }))
    expect(t).toMatch(/Nothing is drafted, approved or applied here/)
    expect(t).toMatch(/happens in remediation/)
  })
})

describe('AssessFileFindings — what passed, and what could not be assessed', () => {
  it('names the passes and the no-method criteria, and prints the identity', async () => {
    const row = rowFor(FILE)
    // 5 selected · 3 failing · 1 passed (1.4.3) · 1 no method (1.3.2)
    const t = text(await mount({ row, file: FILE }))
    expect(t).toMatch(/1 criterion passed/)
    expect(t).toMatch(/1\.4\.3/)
    expect(t).toMatch(/1 criterion could not be assessed/)
    expect(t).toMatch(/1\.3\.2 Meaningful Sequence/)
    expect(t).toMatch(/3 failing \+ 1 passed \+ 1 no method = 5 selected criteria/)
  })

  it('says a no-method criterion is neither a pass nor a failure', async () => {
    const t = text(await mount({ row: rowFor(FILE), file: FILE }))
    expect(t).toMatch(/ACP has no method for this in PDF/)
    expect(t).toMatch(/Not passes, not failures/)
  })

  it('the identity holds for the row it was given', async () => {
    const row = rowFor(FILE)
    const passed = row.criteriaEvaluated.filter((sc) => !row.criteriaFailing.includes(sc))
    expect(row.criteriaFailing.length + passed.length + row.unassessableCriteria.length)
      .toBe(row.selectedChecks)
    const t = text(await mount({ row, file: FILE }))
    expect(t).not.toMatch(/these do not add up/)
  })
})

describe('AssessFileFindings — no score, no percentage, no effort estimate', () => {
  it('renders none of the three', async () => {
    const t = text(await mount({ row: rowFor(FILE), file: FILE, onRemediate: () => {} }))
    expect(t).not.toMatch(/%/)
    expect(t).not.toMatch(/\bscore\b/i)
    expect(t).not.toMatch(/\b\d+(\.\d+)?\s*(hrs?|hours?|mins?|minutes?)\b/i)
    expect(t).not.toMatch(/\best(\.|imated)\b/i)
  })
})

// ── SOURCE LANE ──────────────────────────────────────────────────────────────────────────────
// Claims the DOM cannot carry: the absence of an operation, of an import, of an arithmetic.

describe('AssessFileFindings — source invariants', () => {
  it('contains no sort of its own — the ordering is the metrics module’s decision', () => {
    expect(SRC).not.toMatch(/\.sort\s*\(/)
    // And the band split is a slice, which cannot reorder.
    expect(SRC).toMatch(/\.slice\(/)
  })

  it('imports its numbers and its grouping from assessMetrics, and derives neither', () => {
    expect(SRC).toMatch(/import \{[^}]*documentRow[^}]*findingsByCriterion[^}]*\} from '\.\/assessMetrics\.js'/)
    // No second pass over the raw file's issues: every count comes from the row it was handed.
    expect(SRC).not.toMatch(/\.issues\b/)
    expect(SRC).not.toMatch(/\bassessMetrics\(/)
  })

  it('imports nothing that could generate content', () => {
    for (const forbidden of ['./ai.js', './aiRemediate.js', './aiRemote.js', './autoDraft.js',
                             './refineDraft', './proposal']) {
      expect(SRC).not.toContain(forbidden)
    }
    expect(SRC).not.toMatch(/\bpropose\b/)
    expect(SRC).not.toMatch(/\bexplain\(/)
    expect(SRC).not.toMatch(/aiDraft/)
  })

  it('names all three fix modes, and never calls an assisted fix automatic', () => {
    expect(SRC).toMatch(/auto:\s*'Fixed automatically in remediation'/)
    expect(SRC).toMatch(/assisted:\s*'AI drafts it in remediation, you approve it there'/)
    expect(SRC).toMatch(/human:\s*'You author it in remediation'/)
    // The one place a mode could be widened. `auto` is read from assessMetrics' fixMode and is
    // never computed here from anything else.
    expect(SRC).not.toMatch(/fixMode\s*!==?\s*'human'/)
    expect(SRC).not.toMatch(/fixMode\s*===?\s*'assisted'\s*\|\|/)
  })

  it('contains no percentage, score or effort arithmetic', () => {
    expect(SRC).not.toMatch(/Math\.round\(/)
    expect(SRC).not.toMatch(/\* 100\b/)
    expect(SRC).not.toMatch(/etaMin|manualMin|savingsPct|\bscore\b/)
  })
})
