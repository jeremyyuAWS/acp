/**
 * The file worklist, rendered — the six things it must never do.
 *
 *   · render a row for a run that has not happened;
 *   · put a number on a document it could not open;
 *   · describe that document as excluded, or offer work on it;
 *   · let a filter hide how much it filtered out;
 *   · let the ordering hide anything either — a demoted row keeps every count it had;
 *   · print a percentage, a score, or an estimate of human effort.
 *
 * Everything numeric is asserted from the DOM, because the point of these numbers is to be READ
 * next to each other: the severity partition has to sum to the findings cell ON SCREEN, in the same
 * row, or a reader has no way to tell a broken partition from a true one.
 *
 * The second lane is source assertions, for the one property the DOM cannot show — that the
 * component takes its numbers from `assessMetrics.js` rather than computing its own. A component
 * that recomputes a count renders identically right up until it disagrees.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import AssessWorklist from './AssessWorklist.jsx'

afterEach(unmountAll)

it('renders every document in a bounded scroll region and combines search with file type filters', async () => {
  const c = await mount({ initialFilter: 'all', files: [doc('alpha.docx', [finding('1.1.1')]), doc('beta.pdf', [finding('1.1.1')]), doc('gamma.docx', [finding('1.1.1')]), ...Array.from({length: 6}, (_, i) => doc(`extra${i}.pdf`, [finding('1.1.1')]))] })
  expect(rowsOf(c)).toHaveLength(9)
  expect(c.querySelector('[aria-label="Document findings table"]').classList.contains('document-findings-scroll-all')).toBe(true)
  await act(async () => [...c.querySelectorAll('[aria-label="Filter by file type"] button')].find(b => b.textContent.startsWith('DOCX')).click())
  expect(order(c)).toEqual(['alpha.docx','gamma.docx'])
  const input = c.querySelector('input[type="search"]')
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'GAMMA'); input.dispatchEvent(new Event('input', {bubbles:true})) })
  expect(order(c)).toEqual(['gamma.docx'])
  await act(async () => [...c.querySelectorAll('.sfbar button')].find(b => b.textContent.includes('clear')).click())
  expect(rowsOf(c)).toHaveLength(9)
})

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

const CRITERIA = new Set(['1.1.1', '1.3.1'])
// docx can auto-fix 1.3.1; pptx can auto-fix both; pdf can auto-fix neither. `assisted` is an AI
// draft awaiting approval and counts as review, never as automation.
const CAP = {
  docx: { '1.1.1': 'assisted', '1.3.1': 'auto' },
  pdf: { '1.1.1': 'assisted', '1.3.1': 'human' },
  pptx: { '1.1.1': 'auto', '1.3.1': 'auto' },
}
// pdf has no lane for 1.3.1 at all — that check cannot run against a pdf, which is neither a pass
// nor a failure. docx's 1.1.1 lane is `review`, so a docx with nothing wrong is still awaiting a
// person; only pptx, whose lanes are both `auto`, can come back genuinely clear.
const ASMT = {
  docx: { '1.1.1': 'review', '1.3.1': 'auto' },
  pdf: { '1.1.1': 'review' },
  pptx: { '1.1.1': 'auto', '1.3.1': 'auto' },
}

const doc = (name, issues = [], over = {}) => ({ file: name, name, status: 'analysed', issues, ...over })
const finding = (sc, severity = 'SERIOUS') => ({ wcag: `SC_${sc.replace(/\./g, '_')}`, severity })

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(AssessWorklist, {
      cap: CAP, assessment: ASMT, criteria: CRITERIA, ...props,
    }))
  })
  return container
}

// 3 documents needing attention (6 findings · 3 auto-fix · 3 review), 1 awaiting review,
// 1 with no findings, 1 that could not be opened. Six documents, four states.
const ESTATE = [
  doc('handbook.docx', [finding('1.1.1', 'CRITICAL'), finding('1.3.1', 'SERIOUS'),
                        finding('1.3.1', 'MODERATE')]),
  doc('board.pdf', [finding('1.1.1', 'SERIOUS'), finding('1.1.1', 'MINOR')]),
  doc('deck.pptx', [finding('1.3.1', 'MODERATE')]),
  doc('notes.docx'),
  doc('clean.pptx'),
  doc('locked.pdf', [], { status: 'error', error: 'password-protected' }),
]

const rowsOf = (c) => [...c.querySelectorAll('tbody tr')]
const nameOf = (r) => r.querySelector('td div').textContent
const order = (c) => rowsOf(c).map(nameOf)
const named = (c, name) => rowsOf(c).find((r) => nameOf(r) === name)
const cell = (r, col) => r.querySelector(`.col-${col} .n`).textContent
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.querySelector('.remediation-category-pill')?.getAttribute('aria-label') || b.textContent))
// "Show every row" — the state filter AND, now, the A11 pagination reveal if the filtered set still
// exceeds one page. Existing callers asked for every row to be visible; A11 truncation is additive
// and this keeps that promise rather than making every pre-existing test learn about page size.
const showAll = async (c) => {
  await act(async () => { btn(c, /^All /).click() })
  const more = btn(c, /^Show the other/)
  if (more) await act(async () => { more.click() })
}

describe('nothing to report renders nothing', () => {
  it('renders no markup at all before a run', async () => {
    const c = await mount({ files: null })
    expect(c.textContent).toBe('')
    expect(c.querySelectorAll('*')).toHaveLength(0)
  })

  it('does not render an empty worklist after a failed read', async () => {
    // Not an array — the shape an error response arrives in. A zeroed worklist would read as a
    // completed run over an estate with nothing wrong in it.
    const c = await mount({ files: { detail: 'forbidden' } })
    expect(c.textContent, 'a failed read rendered as a completed run').toBe('')
  })

  it('renders nothing when no document was selected', async () => {
    const c = await mount({ files: [] })
    expect(c.textContent).toBe('')
  })
})

describe('one row per document, in the order the module gave', () => {
  it('keeps that order, unopened last', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(order(c))
      .toEqual(['handbook.docx', 'board.pdf', 'deck.pptx', 'clean.pptx', 'notes.docx', 'locked.pdf'])
  })

  it('shows every column for a document, from the module row', async () => {
    const c = await mount({ files: ESTATE })
    const row = named(c, 'handbook.docx')
    expect(cell(row, 'findings')).toBe('3')
    expect(row.querySelector('.col-category').textContent).toContain('Auto 2')
    expect(row.querySelector('.col-category').textContent).toContain('AI 1')
  })

  it('names the checks that could not run against this format', async () => {
    const c = await mount({ files: ESTATE })
    // pdf has no lane for 1.3.1, so "no findings on the pdf rows" would be a claim about one
    // criterion, not two. Singular, because one criterion is one criterion.
    expect(named(c, 'board.pdf').textContent)
      .toMatch(/1 criterion could not be assessed for this format/)
    expect(named(c, 'handbook.docx').textContent).toMatch(/all 2 selected checks evaluated/)
  })
})

describe('the severity partition sums to the row it sits in', () => {
  it('replaces severity with remediation category counts and SC details', async () => {
    const c = await mount({ files: ESTATE })
    const row = named(c, 'handbook.docx')
    const category = row.querySelector('.col-category')
    expect(category.textContent).toContain('Auto 2')
    expect(category.textContent).toContain('AI 1')
    expect(category.querySelector('details')).toBeNull()
    expect(category.querySelector('[aria-label="Fully automated: 2 findings"]')).not.toBeNull()
    expect(c.querySelector('[aria-label="Remediation category legend"]').textContent).toContain('Fully automated')
    expect(cell(row, 'findings')).toBe('3')
    expect(c.querySelector('th').parentElement.textContent).not.toContain('Severity')
  })

  it('breaks down the work needing a person, in the cell it sums to', async () => {
    const c = await mount({ files: ESTATE })
    const row = named(c, 'handbook.docx')
    expect(row.querySelector('.col-category').textContent).toContain('AI 1')
    expect(row.querySelector('.col-person')).toBeNull()
  })

  it('says None rather than four zeros where there is nothing to partition', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(named(c, 'clean.pptx').textContent).toMatch(/No remaining findings/)
  })
})

describe('the order is what needs a person, not what looks worst', () => {
  // Attention is the only scarce thing on this screen. A finding ACP fixes deterministically costs
  // a reader one button in remediation; a finding needing judgement costs them an afternoon. So the
  // list is ranked by the second, and the first does not buy a document a place at the top.
  const MACHINE = doc('machine.pptx', [finding('1.3.1', 'CRITICAL'), finding('1.3.1', 'CRITICAL')])
  const HUMAN = doc('human.pdf', [finding('1.1.1', 'MODERATE')])

  it('puts a moderate finding needing judgement above two auto-fixable criticals', async () => {
    const c = await mount({ files: [MACHINE, HUMAN] })
    expect(order(c), 'the worklist is ranked by severity rather than by human cost')
      .toEqual(['human.pdf', 'machine.pptx'])
  })

  it('hides nothing it deprioritises', async () => {
    // The failure mode of a de-emphasis rule is that it turns into a filter. Both criticals are
    // still on the row, still counted, still in the totals.
    const c = await mount({ files: [MACHINE, HUMAN] })
    const row = named(c, 'machine.pptx')
    expect(cell(row, 'findings')).toBe('2')
    expect(row.querySelector('.col-auto')).toBeNull()
    expect(row.querySelector('.col-category').textContent).toMatch(/Auto 2/)
    expect(c.textContent).toMatch(/3 findings · 2 auto-fix · 1 needing a person/)
  })

  it('says on the row why it is down there', async () => {
    const c = await mount({ files: [MACHINE, HUMAN] })
    expect(named(c, 'machine.pptx').textContent)
      .toMatch(/Nothing here needs you — ACP fixes all 2 in remediation/)
    expect(named(c, 'human.pdf').textContent).not.toMatch(/Nothing here needs you/)
  })

  it('names the ordering rather than leaving it to be inferred', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent).toMatch(/Grouped by remediation capability/)
  })
})

describe('a document that failed to open is a run outcome, not an exclusion', () => {
  // Discovery is metadata-only and never opens a file, so a password-protected or corrupt document
  // is only discoverable HERE, by trying to read it. That makes it a failure of this run rather
  // than a filter applied before it — and only the second reading tells a reader there is
  // something left to chase.
  it('states the reason it could not be read', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(named(c, 'locked.pdf').textContent).toMatch(/could not be opened — password-protected/)
  })

  it('puts no number on it at all', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    // Not "0 findings, 0 auto-fix": a file ACP never read did not come back clean, and a zero in
    // those columns is indistinguishable from one that did.
    expect(named(c, 'locked.pdf').textContent, 'an unread document carries counts')
      .not.toMatch(/[0-9]/)
  })

  it('offers no work on it', async () => {
    const c = await mount({ files: ESTATE, onOpenFile: vi.fn() })
    await showAll(c)
    expect(named(c, 'locked.pdf').querySelectorAll('button')).toHaveLength(0)
    expect(named(c, 'locked.pdf').textContent).toMatch(/holds no work until the file can be opened/)
  })

  it('does not call it excluded', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(named(c, 'locked.pdf').textContent, 'a failed read is described as an exclusion')
      .not.toMatch(/exclu/i)
    expect(btn(c, /Could not open/).textContent).not.toMatch(/exclu/i)
  })
})

describe('a filter can narrow this list, never hide what it dropped', () => {
  it('opens on the documents holding work', async () => {
    const c = await mount({ files: ESTATE })
    expect(rowsOf(c)).toHaveLength(3)
    expect(btn(c, /Needs attention/).getAttribute('aria-pressed')).toBe('true')
  })

  it('keeps every unselected filter’s count on screen', async () => {
    const c = await mount({ files: ESTATE })
    // The counts of what is NOT being shown are the whole point: a screenshot of a filtered
    // worklist has to carry its own denominator.
    expect(btn(c, /Needs attention/).textContent).toMatch(/Needs attention 3/)
    expect(btn(c, /Awaiting review/).textContent).toMatch(/Awaiting review 1/)
    expect(btn(c, /Could not open/).textContent).toMatch(/Could not open 1/)
    expect(btn(c, /^All /).textContent).toMatch(/All 6/)
  })

  it('names the clear population in the header and offers a Clear tab', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent).toMatch(/1 with no findings/)
    // Clear now has its own tab (user request 2026-08-22)
    expect(btn(c, /^Clear/)).toBeTruthy()
  })

  it('prints the totals it is not showing', async () => {
    const c = await mount({ files: ESTATE })
    await act(async () => { btn(c, /Awaiting review/).click() })
    expect(rowsOf(c)).toHaveLength(1)
    expect(c.textContent)
      .toMatch(/Showing 1 of 6 documents — 0 findings · 0 auto-fix · 0 needing a person/)
    expect(c.textContent, 'a filtered view lost the estate totals')
      .toMatch(/Across all 6: 6 findings · 3 auto-fix · 3 needing a person/)
  })

  it('drops the second line only when nothing is filtered out', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(c.textContent)
      .toMatch(/Showing 6 of 6 documents — 6 findings · 3 auto-fix · 3 needing a person/)
    expect(c.textContent).not.toMatch(/Across all/)
  })

  it('opens on everything when nothing needs attention', async () => {
    // Defaulting to an empty "needs attention" view would read as a worklist with no documents in
    // it, over an estate that has four.
    const c = await mount({ files: [doc('notes.docx'), doc('clean.pptx')] })
    expect(rowsOf(c)).toHaveLength(2)
    expect(btn(c, /^All /).getAttribute('aria-pressed')).toBe('true')
    expect(btn(c, /Needs attention/).disabled, 'an empty filter is still offered').toBe(true)
    expect(btn(c, /Needs attention/).textContent).toMatch(/Needs attention 0/)
  })
})

describe('A19 severity filter and A24 auto-fixable toggle — narrow, never hide what they drop', () => {
  // Both compose on top of the state filter and obey the same rule the state filter does: every
  // count stays on screen whether or not it is the one selected, and a narrowed view still prints
  // the estate totals underneath it. Severity counts are FINDINGS ("Serious 2"), the toggle's
  // denominator is findings AND documents, and neither control invents a number of its own.
  const refineBtn = (c, re) => [...c.querySelectorAll('.worklist-refine button')].find((b) => re.test(b.querySelector('.remediation-category-pill')?.getAttribute('aria-label') || b.textContent))
  const autoInput = (c) => c.querySelector('.worklist-autoonly input')

  it('counts findings by remediation category without dropping zero categories', async () => {
    const c = await mount({ files: ESTATE })
    expect(refineBtn(c, /Fully automated/).textContent).toContain('3')
    expect(refineBtn(c, /AI suggestion needed/).textContent).toContain('3')
    expect(refineBtn(c, /Manual fix required/).textContent).toContain('0')
    expect(refineBtn(c, /Blocked/).disabled).toBe(true)
  })

  it('narrows to the documents holding a finding of the chosen remediation category', async () => {
    const c = await mount({ files: ESTATE })
    await act(async () => { refineBtn(c, /AI suggestion needed/).click() })
    // handbook (serious 1.3.1) and board (serious 1.1.1) hold one; deck.pptx (a lone moderate) does not.
    expect(order(c)).toEqual(['handbook.docx', 'board.pdf'])
  })

  it('still prints the estate totals when a remediation category is chosen', async () => {
    const c = await mount({ files: ESTATE })
    await act(async () => { refineBtn(c, /AI suggestion needed/).click() })
    expect(c.textContent).toMatch(/Showing 2 of 6 documents/)
    expect(c.textContent, 'a severity-filtered view lost the estate totals')
      .toMatch(/Across all 6: 6 findings · 3 auto-fix · 3 needing a person/)
  })

  it('retires the automatic-only filter while preserving its counts and the complete document list', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.querySelector('.worklist-autoonly')).toBeNull()
    expect(c.querySelector('.worklist-auto-counts').textContent).toContain('3 of 6 findings · 2 of 3 documents')
    expect(c.querySelector('.col-auto')).toBeNull()
    expect(c.querySelector('.col-person')).toBeNull()
    expect(order(c)).toContain('board.pdf')
    expect(c.querySelector('.remediation-category-legend').closest('details').open).toBe(false)
  })

  it('offers an empty remediation category but does not let it be chosen', async () => {
    const c = await mount({ files: [doc('a.pptx', [finding('1.3.1', 'CRITICAL')])] })
    // One critical finding and nothing else — the other three severities are shown at zero, so the
    // reader sees they were considered, and disabled, so the list cannot be filtered to nothing.
    expect(refineBtn(c, /Fully automated/).disabled).toBe(false)
    expect(refineBtn(c, /AI suggestion needed/).disabled).toBe(true)
    expect(refineBtn(c, /AI suggestion needed/).textContent).toMatch(/AI 0/)
  })

  it('hides both controls when the state in view has no finding work to narrow', async () => {
    const c = await mount({ files: ESTATE })
    // "Awaiting review" holds one document with no findings; there is nothing for a severity chip
    // or an auto-fix toggle to act on, so the refine bar is not drawn at all.
    await act(async () => { btn(c, /Awaiting review/).click() })
    expect(c.querySelector('.worklist-refine')).toBe(null)
  })

  it('does not render the controls for an estate with nothing to fix', async () => {
    const c = await mount({ files: [doc('notes.docx'), doc('clean.pptx')] })
    expect(c.querySelector('.worklist-refine')).toBe(null)
  })
})

describe('A11 progressive disclosure — a page can narrow what renders, never what it hid', () => {
  // Seven documents needing attention, each with a distinct number of findings, so "the other 2"
  // sums to a checkable, non-trivial total (2 + 3 = 5, from the last two of the seven).
  const SEVEN = Array.from({ length: 7 }, (_, i) =>
    doc(`doc${i}.docx`, Array.from({ length: i + 1 }, () => finding('1.1.1', 'CRITICAL'))))

  it('shows the first page and names what the page — not the filter — is hiding', async () => {
    // documentRows ranks by severity weight DESCENDING, so doc6 (7 findings) leads and doc0
    // (1 finding) trails. The page shows the five heaviest; "the other 2" are the two lightest —
    // doc1 (2 findings) and doc0 (1 finding) — summing to 3.
    const c = await mount({ files: SEVEN, scrollAll: false })
    await act(async () => { btn(c, /^All /).click() })
    expect(rowsOf(c)).toHaveLength(5)
    expect(order(c)).toEqual(['doc6.docx', 'doc5.docx', 'doc4.docx', 'doc3.docx', 'doc2.docx'])
    expect(c.textContent).toMatch(/5 of 7 documents shown/)
    expect(c.textContent).toMatch(/Show the other 2, which hold 3 findings between them/)
  })

  it('reveals every row on demand, and the page-hidden line disappears', async () => {
    const c = await mount({ files: SEVEN, scrollAll: false })
    await act(async () => { btn(c, /^All /).click() })
    await act(async () => { btn(c, /^Show the other/).click() })
    expect(rowsOf(c)).toHaveLength(7)
    expect(c.textContent).not.toMatch(/Show the other/)
  })

  it('does not truncate a set that already fits on one page', async () => {
    const c = await mount({ files: SEVEN.slice(0, 5), scrollAll: false })
    await act(async () => { btn(c, /^All /).click() })
    expect(rowsOf(c)).toHaveLength(5)
    expect(c.textContent).not.toMatch(/Show the other/)
  })

  it('leaves the FILTER summary line (what the filter hid) untouched by pagination', async () => {
    // The existing "Showing X of Y" line answers a different question — what the filter is not
    // showing — and must keep counting the full filtered set, not just the current page.
    const c = await mount({ files: SEVEN })
    await act(async () => { btn(c, /^All /).click() })
    expect(c.textContent).toMatch(/Showing 7 of 7 documents/)
  })
})

describe('A28 bulk select — only ever the deterministic fixes, never an AI draft', () => {
  // Default "Needs attention" view: handbook.docx (2 auto, 1 needs a person), board.pdf (0 auto —
  // both its findings are AI-drafted 'assisted', never selectable), deck.pptx (1 auto).
  const checkboxIn = (row) => row.querySelector('input[type="checkbox"]')

  it('offers a checkbox only on a row with a deterministic fix — never on 0-auto or unopened', async () => {
    const c = await mount({ files: ESTATE, onBulkFix: vi.fn() })
    expect(checkboxIn(named(c, 'handbook.docx')), 'no checkbox on a document with an auto-fix').toBeTruthy()
    expect(checkboxIn(named(c, 'deck.pptx'))).toBeTruthy()
    expect(checkboxIn(named(c, 'board.pdf')), 'board.pdf has 0 deterministic findings — assisted only')
      .toBe(null)
  })

  it('renders no selection checkboxes in the table when the caller offers no bulk action', async () => {
    // A24's own "only auto-fixable" toggle is ALSO a checkbox and is unrelated to A28 — it lives in
    // the refine bar, not the table. Scoped to the table body/head specifically.
    const c = await mount({ files: ESTATE })
    expect(c.querySelectorAll('table input[type="checkbox"]')).toHaveLength(0)
  })

  it('shows the selection bar naming the documents and the deterministic findings, once picked', async () => {
    const c = await mount({ files: ESTATE, onBulkFix: vi.fn() })
    expect(c.querySelector('.worklist-bulkbar'), 'the bar must not show with nothing picked').toBe(null)
    await act(async () => { checkboxIn(named(c, 'handbook.docx')).click() })
    const bar = c.querySelector('.worklist-bulkbar')
    expect(bar).toBeTruthy()
    expect(bar.textContent).toMatch(/1 document selected/)
    // handbook.docx: 2 deterministic (1.3.1 x2), never the 1 assisted 1.1.1 finding.
    expect(bar.textContent).toMatch(/Fix 2 findings/)
  })

  it('sums across the selection, and pluralises the document count correctly', async () => {
    const c = await mount({ files: ESTATE, onBulkFix: vi.fn() })
    await act(async () => { checkboxIn(named(c, 'handbook.docx')).click() })
    await act(async () => { checkboxIn(named(c, 'deck.pptx')).click() })
    const bar = c.querySelector('.worklist-bulkbar')
    expect(bar.textContent).toMatch(/2 documents selected/)
    expect(bar.textContent).toMatch(/Fix 3 findings/)   // 2 (handbook) + 1 (deck)
  })

  it('hands back the whole picked rows, not just names, when Fix is clicked', async () => {
    const onBulkFix = vi.fn()
    const c = await mount({ files: ESTATE, onBulkFix })
    await act(async () => { checkboxIn(named(c, 'handbook.docx')).click() })
    await act(async () => { [...c.querySelectorAll('.worklist-bulkbar button')].find((b) => /^Fix/.test(b.textContent)).click() })
    expect(onBulkFix).toHaveBeenCalledTimes(1)
    const rows = onBulkFix.mock.calls[0][0]
    expect(rows).toHaveLength(1)
    expect(rows[0].file).toBe('handbook.docx')
    expect(rows[0].autoFixAvailable).toBe(2)
  })

  it('clears the selection and hides the bar again', async () => {
    const c = await mount({ files: ESTATE, onBulkFix: vi.fn() })
    await act(async () => { checkboxIn(named(c, 'handbook.docx')).click() })
    await act(async () => { [...c.querySelectorAll('.worklist-bulkbar button')].find((b) => /Clear/.test(b.textContent)).click() })
    expect(c.querySelector('.worklist-bulkbar')).toBe(null)
  })

  it('select-all picks every selectable row on the page and only those', async () => {
    const c = await mount({ files: ESTATE, onBulkFix: vi.fn() })
    const headerBox = c.querySelector('thead input[type="checkbox"]')
    expect(headerBox, 'no select-all control').toBeTruthy()
    await act(async () => { headerBox.click() })
    expect(checkboxIn(named(c, 'handbook.docx')).checked).toBe(true)
    expect(checkboxIn(named(c, 'deck.pptx')).checked).toBe(true)
    expect(c.querySelector('.worklist-bulkbar').textContent).toMatch(/2 documents selected/)
  })

  it('offers no select-all when nothing on the page is selectable', async () => {
    // "Awaiting review" holds documents with zero findings — nothing to bulk-fix.
    const c = await mount({ files: ESTATE, onBulkFix: vi.fn() })
    await act(async () => { btn(c, /Awaiting review/).click() })
    expect(c.querySelector('thead input[type="checkbox"]')).toBe(null)
  })
})

describe('selecting a document', () => {
  it('hands the whole module row back, not a name', async () => {
    const onOpenFile = vi.fn()
    const c = await mount({ files: ESTATE, onOpenFile })
    await act(async () => { named(c, 'handbook.docx').querySelector('button').click() })
    expect(onOpenFile).toHaveBeenCalledTimes(1)
    const row = onOpenFile.mock.calls[0][0]
    expect(row.file).toBe('handbook.docx')
    // The next screen down groups these by criterion; handing it the row means it reads the same
    // numbers this one printed rather than counting the file a second time.
    expect(row.totalFindings).toBe(3)
    expect(row.criteriaFailing).toEqual(['1.1.1', '1.3.1'])
  })

  it('offers a document with no findings too, in its own words', async () => {
    const c = await mount({ files: ESTATE, onOpenFile: vi.fn() })
    await showAll(c)
    expect(named(c, 'handbook.docx').querySelector('button').textContent).toMatch(/Open findings/)
    expect(named(c, 'clean.pptx').querySelector('button').textContent).toMatch(/Open document/)
  })

  it('offers nothing to click when there is nowhere to go', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(rowsOf(c).flatMap((r) => [...r.querySelectorAll('button')])).toHaveLength(0)
  })
})

describe('what this panel is not allowed to show', () => {
  it('shows no score', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(c.textContent, 'a score is back on the worklist').not.toMatch(/score/i)
    expect(c.textContent).not.toMatch(/\/\s*100\b/)
  })

  it('shows no percentage', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(c.textContent, 'a bare percentage is back').not.toMatch(/%/)
  })

  it('shows no estimate of human effort', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(c.textContent, 'a time estimate is back')
      .not.toMatch(/\b(hrs?|hours?|min(ute)?s?|per person|effort)\b/i)
  })
})

describe('what the component is not allowed to derive itself', () => {
  const src = read('AssessWorklist.jsx')

  it('takes every number from the metric module', () => {
    expect(src).toMatch(/from '\.\/assessMetrics\.js'/)
    expect(src, 'the component filters findings itself').not.toMatch(/\.issues\b/)
    expect(src, 'the component counts files itself').not.toMatch(/files\.(filter|length|reduce|map)/)
  })

  it('uses scoped findings for category and SC disclosure', async () => {
    // Category/SC disclosure uses already-scoped findings from documentRows.
    expect(src).toContain('remediationCategory(finding)')
    expect(src).not.toMatch(/\.issues\b/)
    expect(src).toContain('<RemediationCategoryPill')
  })

  it('does not impose a second ordering on the list', () => {
    // documentRows already ranks the estate, unopened last. A sort here would be a second rule for
    // the same list, and the two would drift.
    expect(src, 'the worklist re-sorts the module’s order').not.toMatch(/\.sort\(/)
  })
})


it('labels the screenshot category total as 23 findings and keeps change records separate', async () => {
  const c = await mount({ files: [
    doc('automatic.docx', Array.from({length:11}, () => finding('1.3.1'))),
    doc('suggestions.docx', Array.from({length:6}, () => finding('1.1.1'))),
    doc('manual.pdf', Array.from({length:6}, () => finding('1.3.1'))),
  ] })
  expect(c.textContent).toContain('23 assessed findings across the document categories')
  expect(c.textContent).toContain('Change records are separate and are not added to findings')
})
