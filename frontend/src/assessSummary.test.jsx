/**
 * The summary panel, rendered — the four things it must never do.
 *
 *   · render zeros for a run that has not happened;
 *   · say "No findings" without the coverage caveat when checks did not run;
 *   · print a percentage, a score, or an estimate of human effort;
 *   · print a partition that does not add up to its whole.
 *
 * The arithmetic lines are asserted from the DOM rather than from `reconcile()` because their whole
 * purpose is to be READ. A sum that is correct in a unit test and absent from the page protects
 * nobody.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import AssessSummary from './AssessSummary.jsx'

afterEach(unmountAll)

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

const CRITERIA = new Set(['1.1.1', '1.3.1'])
const CAP = { docx: { '1.1.1': 'assisted', '1.3.1': 'auto' }, pdf: { '1.1.1': 'assisted', '1.3.1': 'human' } }
const ASMT = { docx: { '1.1.1': 'review', '1.3.1': 'auto' }, pdf: { '1.1.1': 'review' } }

const doc = (name, issues = [], over = {}) => ({ file: name, name, status: 'analysed', issues, ...over })
const finding = (sc, severity = 'SERIOUS') => ({ wcag: `SC_${sc.replace(/\./g, '_')}`, severity })

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(AssessSummary, {
      cap: CAP, assessment: ASMT, criteria: CRITERIA, ...props,
    }))
  })
  return container
}

const ESTATE = [
  doc('a.docx', [finding('1.1.1', 'CRITICAL'), finding('1.3.1', 'SERIOUS')]),
  doc('b.pdf', [finding('1.1.1', 'MODERATE')]),
  doc('c.docx'),
  doc('locked.pdf', [], { status: 'error', error: 'password-protected' }),
]

describe('nothing to report renders nothing', () => {
  it('renders no markup at all before a run', async () => {
    const c = await mount({ files: null })
    expect(c.textContent).toBe('')
    expect(c.querySelectorAll('*')).toHaveLength(0)
  })

  it('does not render a zeroed summary after a failed read', async () => {
    const c = await mount({ files: { detail: 'forbidden' } })
    expect(c.textContent, 'a failed read rendered as a completed run').toBe('')
  })
})

describe('the three facts that replace the score', () => {
  it('leads with a status, a coverage fraction and a finding sentence', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent).toMatch(/Needs attention/)
    // 2 of 2: the docx rows carry a lane for both criteria, even though the pdf carries one.
    // Coverage is per criterion across the estate, not per document.
    expect(c.textContent).toMatch(/2 of 2 selected criteria evaluated/)
    expect(c.textContent).toMatch(/3 across 2 documents/)
  })

  it('shows no score anywhere', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent, 'a score is back on the summary').not.toMatch(/score/i)
    expect(c.textContent).not.toMatch(/\/\s*100\b/)
  })

  it('shows no percentage', async () => {
    // Every percentage on the old screen lacked a denominator. Counts throughout instead.
    const c = await mount({ files: ESTATE })
    expect(c.textContent, 'a bare percentage is back').not.toMatch(/%/)
  })

  it('shows no estimate of human effort', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent, 'a time estimate is back')
      .not.toMatch(/\b(hrs?|hours?|min(ute)?s?|per person)\b/i)
  })
})

describe('“no findings” never travels alone', () => {
  const CLEAN = [doc('a.pdf')]   // 1.3.1 has no lane for pdf, so a check could not run

  it('carries the caveat when a selected check could not run', async () => {
    // `a.pdf` has a review lane for 1.1.1 and none for 1.3.1, so this is the AWAITING-REVIEW
    // state, not `clear` — and the first version of the caveat was gated on the status name, so
    // exactly this run rendered a clean-looking summary with no caveat at all.
    const c = await mount({ files: CLEAN })
    expect(c.textContent).toMatch(/Awaiting review/)
    expect(c.textContent, 'a clean-looking run with gaps printed no caveat')
      .toMatch(/not the same as conformant/i)
    expect(c.textContent).toMatch(/1 of 2 selected checks could not run/)
  })

  it('names a document that failed to open, in the caveat', async () => {
    const c = await mount({ files: [doc('a.pdf'), doc('locked.pdf', [], { status: 'error' })] })
    expect(c.textContent).toMatch(/1 document failed to open/)
  })

  it('carries it in the no-findings state too', async () => {
    // Both criteria have a lane on docx, so nothing is missed here — but add an unopened file and
    // the run is once again not the clean bill of health it looks like.
    const c = await mount({ files: [doc('a.docx'), doc('locked.docx', [], { status: 'error' })] })
    expect(c.textContent).toMatch(/No findings/)
    expect(c.textContent).toMatch(/not the same as conformant/i)
  })

  it('drops the caveat only when nothing was missed', async () => {
    // A docx has a lane for both criteria, so this run really did evaluate everything selected.
    const c = await mount({ files: [doc('a.docx')] })
    expect(c.textContent).not.toMatch(/not the same as conformant/i)
  })
})

describe('the arithmetic is on the page, not just in a test', () => {
  it('prints the finding partition', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent).toMatch(/1 auto-fixable \+ 2 needing review = 3 findings/)
  })

  it('prints the check partition with both factors of the denominator', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent).toMatch(/= 6 selected checks \(3 documents × 2 criteria\)/)
  })

  it('shows severity summing to the finding total', async () => {
    const c = await mount({ files: ESTATE })
    // 1 critical + 1 serious + 1 moderate + 0 minor = 3 findings, which is the printed total.
    expect(c.textContent).toMatch(/1 critical/)
    expect(c.textContent).toMatch(/1 serious/)
    expect(c.textContent).toMatch(/1 moderate/)
    expect(c.textContent).toMatch(/0 minor/)
  })

  it('A6 · prints the severity partition as an equation, all four addends, summing to the total', async () => {
    const c = await mount({ files: ESTATE })
    // The words are already there per-severity; the equation makes the partition checkable at a
    // glance against Total findings, and includes the zero so the four addends are always four.
    expect(c.querySelector('.assesssummary-sevsum').textContent).toMatch(/1 \+ 1 \+ 1 \+ 0 = 3/)
  })

  it('A6 · prints no equation when there is nothing to add', async () => {
    // A run that found nothing has no partition; an equation "0 + 0 + 0 + 0 = 0" would be noise on a
    // clean result and read like a scoreboard of zeros.
    const c = await mount({ files: [doc('c.docx')] })
    expect(c.querySelector('.assesssummary-sevsum')).toBe(null)
  })
})

describe('A1 · what the run was, before its numbers', () => {
  it('names the screen and states the level and criteria scope', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.querySelector('.assesssummary-head').textContent).toMatch(/Assessment results/)
    // The level is STATED, never a control; the criteria count is the selected scope, the same
    // denominator the coverage sentence reads against — so the two can never disagree.
    expect(c.querySelector('.assesssummary-head').textContent)
      .toMatch(/WCAG 2\.1 Level AA · 2 selected criteria/)
  })

  it('renders the assessed timestamp when given, and no orphan separator when not', async () => {
    const withStamp = await mount({ files: ESTATE, assessedAt: '20 Aug, 16:44' })
    expect(withStamp.querySelector('.assesssummary-head').textContent)
      .toMatch(/20 Aug, 16:44 · WCAG 2\.1 Level AA/)
    // Absent stamp: the line starts at the level, with no leading " · " where the date would be.
    const noStamp = await mount({ files: ESTATE })
    expect(noStamp.querySelector('.assesssummary-head').textContent).toMatch(/^Assessment resultsWCAG 2\.1/)
  })

  it('states the level it was given rather than a constant', async () => {
    const c = await mount({ files: ESTATE, level: 'AAA' })
    expect(c.querySelector('.assesssummary-head').textContent).toMatch(/WCAG 2\.1 Level AAA/)
  })
})

describe('a document that failed to open is a run outcome, not an exclusion', () => {
  // Deva, 20 Aug: everything knowable up front should already be out of scope before the run, so
  // the results screen must not present a second exclusion list. Discovery is metadata-only and
  // never opens a file, so password protection and corruption are only discoverable HERE — which
  // makes these failures of this run rather than filters applied to it. The distinction is not
  // pedantry: an exclusion reads as "we chose not to", and a failure reads as "we could not",
  // and only the second one tells a reader there is something left to chase.
  it('lists the file and the reason as a failure of this run', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent).toMatch(/1 document failed to open during this run/)
    expect(c.textContent).toMatch(/locked\.pdf — password-protected/)
  })

  it('does not describe them as excluded', async () => {
    // Scoped to THIS panel, not the whole screen. The first draft banned /exclu/i everywhere and
    // caught "Excludes AI-drafted suggestions" on the auto-fix card — which is a metric
    // definition doing exactly its job. What is forbidden is calling a failed READ an exclusion,
    // and that claim lives in one place.
    const c = await mount({ files: ESTATE })
    const panel = [...c.querySelectorAll('div')]
      .map((d) => d.textContent)
      .find((t) => /failed to open during this run/.test(t) && t.length < 400) || ''
    expect(panel, 'the failed-to-open panel calls them excluded').not.toMatch(/exclu/i)
    expect(panel).toMatch(/selected for assessment and produced no verdict/i)
  })

  it('does not qualify the assessed count with a second denominator', async () => {
    // "20 of 22" was what made a failed read look like an exclusion applied before the run.
    const c = await mount({ files: ESTATE })
    expect(c.textContent, 'the assessed count still carries an "of N"').not.toMatch(/3 of 4/)
  })

  it('says nothing when every document opened', async () => {
    const c = await mount({ files: [doc('a.docx')] })
    expect(c.textContent).not.toMatch(/failed to open/)
  })
})

describe('one primary action', () => {
  it('offers remediation when there is something to remediate', async () => {
    const onRemediate = vi.fn()
    const c = await mount({ files: ESTATE, onRemediate })
    const b = [...c.querySelectorAll('button')].filter((x) => /Start remediation/.test(x.textContent))
    expect(b).toHaveLength(1)
    await act(async () => { b[0].click() })
    expect(onRemediate).toHaveBeenCalled()
  })

  it('offers no remediation when there is nothing to remediate', async () => {
    const c = await mount({ files: [doc('a.docx')], onRemediate: vi.fn() })
    expect(c.textContent).not.toMatch(/Start remediation/)
  })

  it('never offers to re-run the assessment from here', async () => {
    // The old screen carried "Re-assess 4 files" as a second prominent button, so nothing on the
    // page said which action finished the job.
    const c = await mount({ files: ESTATE, onRemediate: vi.fn(), onRunDetails: vi.fn() })
    expect(c.textContent, 'a re-assess action competes with remediation').not.toMatch(/re-?assess/i)
  })

  it('keeps run details secondary rather than absent', async () => {
    const onRunDetails = vi.fn()
    const c = await mount({ files: ESTATE, onRunDetails })
    const b = [...c.querySelectorAll('button')].find((x) => /Run details/.test(x.textContent))
    expect(b.className).toMatch(/ghost/)
    await act(async () => { b.click() })
    expect(onRunDetails).toHaveBeenCalled()
  })
})

describe('what the component is not allowed to derive itself', () => {
  it('takes every number from the metric module', () => {
    // Asserted at the source: a component that recomputes a count is a fifth denominator waiting
    // to happen, and that is the defect this whole change exists to remove.
    const src = read('AssessSummary.jsx')
    expect(src).toMatch(/from '\.\/assessMetrics\.js'/)
    expect(src, 'the component filters findings itself').not.toMatch(/\.issues\b/)
    expect(src, 'the component counts files itself').not.toMatch(/files\.(filter|length|reduce)/)
  })
})
