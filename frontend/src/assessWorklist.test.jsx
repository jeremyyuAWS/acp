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
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
const showAll = async (c) => { await act(async () => { btn(c, /^All /).click() }) }

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
    expect(cell(row, 'auto'), '1.3.1 is deterministic on docx, twice').toBe('2')
    expect(cell(row, 'person'), 'the assisted 1.1.1 draft needs judgement').toBe('1')
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
  it('names each severity and adds up to that row’s finding count', async () => {
    const c = await mount({ files: ESTATE })
    const row = named(c, 'handbook.docx')
    // The colour is shorthand for sighted readers; the word is always in the DOM, so four dots
    // never reach a screen reader as "1 1 1 0".
    const sev = row.querySelector('.col-severity').textContent
    for (const [n, s] of [[1, 'critical'], [1, 'serious'], [1, 'moderate'], [0, 'minor']]) {
      expect(sev, `${s} missing from the row`).toMatch(new RegExp(`${n} ${s}`))
    }
    // 1 + 1 + 1 + 0 = 3, which is the Findings cell in the same row.
    expect(cell(row, 'findings')).toBe('3')
  })

  it('breaks down the work needing a person, in the cell it sums to', async () => {
    const c = await mount({ files: ESTATE })
    // Two documents showing "3" here are not the same afternoon when one of them is criticals.
    const person = named(c, 'handbook.docx').querySelector('.col-person')
    expect(person.textContent).toMatch(/1 critical needing a person/)
    expect(cell(named(c, 'handbook.docx'), 'person')).toBe('1')
  })

  it('says None rather than four zeros where there is nothing to partition', async () => {
    const c = await mount({ files: ESTATE })
    await showAll(c)
    expect(named(c, 'clean.pptx').textContent).toMatch(/None/)
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
    expect(cell(row, 'auto')).toBe('2')
    expect(row.querySelector('.col-severity').textContent).toMatch(/2 critical/)
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
    expect(c.textContent).toMatch(/Ordered by what needs a person/)
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
    expect(btn(c, /Failed to open/).textContent).not.toMatch(/exclu/i)
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
    expect(btn(c, /Failed to open/).textContent).toMatch(/Failed to open 1/)
    expect(btn(c, /^All /).textContent).toMatch(/All 6/)
  })

  it('names the population that has no filter button of its own', async () => {
    const c = await mount({ files: ESTATE })
    // `clear` documents are not a filter — there is no work in them — but dropping the count
    // would mean one sixth of the estate appears nowhere on this panel.
    expect(c.textContent).toMatch(/1 with no findings/)
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

  it('does not reach inside a row’s findings', () => {
    // The per-criterion grouping is the next screen down and has its own module function. Counting
    // findings here is how the worklist and the file view start disagreeing about one document.
    expect(src, 'the worklist walks the findings array').not.toMatch(/\.findings\b/)
  })

  it('does not impose a second ordering on the list', () => {
    // documentRows already ranks the estate, unopened last. A sort here would be a second rule for
    // the same list, and the two would drift.
    expect(src, 'the worklist re-sorts the module’s order').not.toMatch(/\.sort\(/)
  })
})
