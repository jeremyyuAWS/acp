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

  it('shows no score anywhere — only the deliberate statement that one is absent', async () => {
    const c = await mount({ files: ESTATE })
    // The board-4 explainer cell says "No accessibility score" by name; that is a declaration of
    // absence, not a leak. What must never appear is an actual score VALUE.
    expect(c.textContent).toMatch(/No accessibility score/)
    expect(c.textContent, 'a score is back on the summary').not.toMatch(/\bscore[d:]?\s*[:=]?\s*\d/i)
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

describe('the seven screen states — a run that did not complete never reads as one that did', () => {
  const gridShown = (c) => /Findings by severity/.test(c.textContent)

  describe('state 6 · assessment failed', () => {
    it('renders no metric grid — not even zeros — for an errored run', async () => {
      // A grid of zeros is the same false verdict as a completed run that found nothing. This state
      // reached no terminal check, so it states that and shows no numbers.
      const c = await mount({ files: ESTATE, run: { status: 'error' } })
      expect(c.textContent).toMatch(/Assessment could not run/)
      expect(gridShown(c), 'a failed run rendered the metric grid').toBe(false)
      expect(c.textContent).not.toMatch(/\b0\b/)
      expect(c.textContent).toMatch(/nothing was changed/)
    })

    it('is failed when no document opened, even without a run status', async () => {
      const c = await mount({ files: [doc('locked.pdf', [], { status: 'error', error: 'password-protected' })] })
      expect(c.textContent).toMatch(/Assessment could not run/)
      expect(gridShown(c)).toBe(false)
    })

    it('offers reconnect and keeps the previous results reachable via run details', async () => {
      const onReconnect = vi.fn(); const onRunDetails = vi.fn()
      const c = await mount({ files: ESTATE, run: { status: 'error' }, onReconnect, onRunDetails })
      await act(async () => { [...c.querySelectorAll('button')].find((b) => /Reconnect/.test(b.textContent)).click() })
      expect(onReconnect).toHaveBeenCalled()
      expect([...c.querySelectorAll('button')].some((b) => /Run details/.test(b.textContent))).toBe(true)
    })
  })

  describe('state 7 · nothing matched the scope', () => {
    it('states the cause and never renders a grid of zeros', async () => {
      const c = await mount({ files: [], discovered: 12408 })
      expect(c.textContent).toMatch(/Nothing to assess/)
      expect(c.textContent, 'the discovered total is not stated').toMatch(/12,408 files/)
      expect(c.textContent).toMatch(/\.docx, \.pdf, \.pptx or \.xlsx/)
      expect(gridShown(c)).toBe(false)
    })

    it('offers the controls that change the scope', async () => {
      let changed = null
      const c = await mount({ files: [], onChangeScope: (which) => { changed = which } })
      await act(async () => { [...c.querySelectorAll('button')].find((b) => /Change document types/.test(b.textContent)).click() })
      expect(changed).toBe('types')
    })
  })

  describe('state 4 · partially completed', () => {
    it('names the assessed denominator ONCE at the top, before any metric', async () => {
      // Every number below is of the documents that ran, not of the scope selected. ESTATE opens 3
      // of its 4 (locked.pdf could not be read), so a cancelled run assessed 3.
      const c = await mount({ files: ESTATE, run: { status: 'cancelled' } })
      const banner = c.querySelector('.assesssummary-partial')
      expect(banner, 'no partial banner').toBeTruthy()
      expect(banner.textContent).toMatch(/Partially completed — 3 documents assessed/)
      expect(banner.textContent).toMatch(/of the 3 assessed/)
    })

    it('still shows the metrics — a partial run reports what it has, it just captions it', async () => {
      const c = await mount({ files: ESTATE, run: { status: 'interrupted' } })
      expect(gridShown(c), 'partial dropped the metrics entirely').toBe(true)
    })

    it('names the not-started count when the caller knows it', async () => {
      const c = await mount({ files: ESTATE, run: { status: 'cancelled' }, notStarted: 13 })
      expect(c.querySelector('.assesssummary-partial').textContent)
        .toMatch(/13 selected documents were never started/)
    })

    it('does not invent a not-started count when it is unknown', async () => {
      const c = await mount({ files: ESTATE, run: { status: 'cancelled' } })
      expect(c.querySelector('.assesssummary-partial').textContent).not.toMatch(/never started/)
    })
  })

  it('a completed run renders exactly as before — no banner, full grid', async () => {
    const c = await mount({ files: ESTATE, run: { status: 'done' } })
    expect(c.querySelector('.assesssummary-partial')).toBe(null)
    expect(c.querySelector('.assesssummary-failed')).toBe(null)
    expect(gridShown(c)).toBe(true)
    expect(c.textContent).toMatch(/Needs attention/)
  })
})

describe('board 7 state 5 — a gap named at the top, not only in the list at the bottom', () => {
  it('names a gap at the top when the run also has findings (overlays state 2)', async () => {
    // ESTATE has findings (a.docx, b.pdf) AND a document that failed to open (locked.pdf) — the
    // no-findings caveat above does not fire here, so without this banner the gap sits only in the
    // per-file list at the very bottom, under every total it qualifies.
    const c = await mount({ files: ESTATE })
    const banner = c.querySelector('.assesssummary-gaps')
    expect(banner, 'no top-of-page gap banner for a run with findings AND a gap').toBeTruthy()
    expect(banner.textContent).toMatch(/could not be assessed/)
    expect(banner.textContent).toMatch(/1 document could not be opened/)
  })

  it('does not render the gap banner for a clean run with no gaps', async () => {
    const c = await mount({ files: [doc('clean.docx', [], {})] })
    expect(c.querySelector('.assesssummary-gaps')).toBe(null)
  })
})

describe('board 4 · the 8th cell names what the score would have been', () => {
  it('states the absence by name, in the metrics grid', async () => {
    const c = await mount({ files: ESTATE })
    expect(c.textContent).toMatch(/Deliberately absent/)
    expect(c.textContent).toMatch(/No accessibility score · no percentages · no time-per-person estimate/)
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

// ── merged from AssessSummary.test.jsx (#721) ────────────────────────────────
// These four arrived in a SECOND test file for this component, named
// AssessSummary.test.jsx — differing from this one only in the case of its first
// letter. On a case-insensitive filesystem (macOS, core.ignorecase=true) both index
// entries map to one physical file, so only one of the two could ever exist on disk,
// and vitest.config.js discovers by glob over files that EXIST. The result: these
// assertions ran in CI on Linux and on no developer machine, while the uppercase path
// reported permanently "modified" in every worktree in the repo.
//
// They keep their own fixtures rather than being rewritten onto this file's `mount`
// helper: they assert about the run's scope, not about criteria coverage, and the
// point of the merge is to relocate them unchanged, not to restate them.
describe('lifecycle exclusion count in the header', () => {
  const LC_CRITERIA = new Set(['1.1.1'])
  const LC_CAP = { docx: { '1.1.1': 'auto' } }
  const LC_ASMT = { docx: { '1.1.1': 'auto' } }
  const LC_FILES = [{ file: 'a.docx', name: 'a.docx', status: 'analysed', issues: [] }]

  async function render(props) {
    const { root, container } = createTestRoot()
    await act(async () => {
      root.render(createElement(AssessSummary, { files: LC_FILES, cap: LC_CAP, assessment: LC_ASMT,
                                                 criteria: LC_CRITERIA, ...props }))
    })
    return container
  }

  it('shows the excluded count when lifecycle_eligible_excluded is non-zero', async () => {
    const run = { status: 'done', scope: { lifecycle_eligible_excluded: 7 } }
    const c = await render({ run })
    expect(c.textContent).toMatch(/7 excluded by lifecycle policy/)
  })

  it('omits the exclusion note when lifecycle_eligible_excluded is zero', async () => {
    const run = { status: 'done', scope: { lifecycle_eligible_excluded: 0 } }
    const c = await render({ run })
    expect(c.textContent).not.toMatch(/excluded by lifecycle policy/)
  })

  it('omits the exclusion note when run has no scope', async () => {
    const c = await render({ run: { status: 'done' } })
    expect(c.textContent).not.toMatch(/excluded by lifecycle policy/)
  })

  it('omits the exclusion note when run is absent', async () => {
    const c = await render({})
    expect(c.textContent).not.toMatch(/excluded by lifecycle policy/)
  })
})
